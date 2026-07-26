# Semantic builder source note: soundbank, Wwise 2021.1

- family: `soundbank`
- status: `grounded`
- notebook id: `wwise-2021.1.14-docs`
- version target: `2021.1`
- gate evidence path: `references/semantic/2021.1/semantic-builder-notebooklm-gate.md`
- official URL status: `evidence-candidate`

## Official/source URLs

- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_soundbank_getinclusions.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_soundbank_setinclusions.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_soundbank_generate.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_soundbank_generated.html
- https://www.audiokinetic.com/en/public-library/2021.1.14_8108/?id=ak_wwise_core_soundbank_generationdone.html

## Endpoint inventory

- `ak.wwise.core.soundbank.getInclusions`
- `ak.wwise.core.soundbank.setInclusions`
- `ak.wwise.core.soundbank.generate`
- `ak.wwise.core.soundbank.generated`
- `ak.wwise.core.soundbank.generationDone`

## Required fields

- `ak.wwise.core.soundbank.getInclusions: soundbank`
- `ak.wwise.core.soundbank.setInclusions: soundbank, operation, inclusions`
- `ak.wwise.core.soundbank.generate: no required fields when generating all, otherwise identify supplied soundbanks`
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
- `infoFile, bankData, pluginInfo, and return array for generated topic options; the 2021.1 publish payload spells the returned plug-in document PluginInfo`

## Return shape

getInclusions returns an inclusions array. setInclusions and generate return strict empty JSON objects. generated publishes soundbank, platform, language, and error details with optional bankInfo, bankData, or capitalized PluginInfo. generationDone publishes optional logs and a deprecated error string.

## Destructive behavior

Mutating. setInclusions with replace and an empty list clears SoundBank inclusions. clearAudioFileCache deletes the audio file cache before conversion. Generation can overwrite on-disk bank and media files.

## Ambiguity constraints

If soundbanks is omitted or empty during generation, Wwise generates all user-defined SoundBanks. Auto-defined SoundBanks cannot be manually specified in the soundbanks array. generated can publish multiple times during one generation request.

## Unsupported cases

Do not include profiler, transport, soundengine, UI, CLI, remote, or debug APIs. Do not treat generationDone as proof that soundbank.generate has fully completed. Do not assume object size fields are accurate until SoundBanks have been generated.

## Cited required fields

- `ak.wwise.core.soundbank.getInclusions: soundbank`
- `ak.wwise.core.soundbank.setInclusions: soundbank, operation, inclusions`
- `ak.wwise.core.soundbank.generate: no required fields when generating all, otherwise identify supplied soundbanks`
- `ak.wwise.core.soundbank.generated: topic payload only`
- `ak.wwise.core.soundbank.generationDone: topic payload only`

## Evidence caveat

NotebookLM returned source-grounded 2021.1 details for this family from notebook `wwise-2021.1.14-docs`. Exact full URLs were not directly surfaced in the browser answer, so the URLs above are versioned public-library candidates and exact page ids; they should be treated as source evidence, not behavioral proof.
