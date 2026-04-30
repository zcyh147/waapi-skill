# Semantic builder source note: soundbank

- family: `soundbank`
- status: `grounded`
- notebook id: `wwise-2022.1-docs`
- version target: `2022.1`

## NotebookLM gate evidence

- Evidence path: `references/semantic-builder-notebooklm-gate.md`
- Unlock rule: this note unlocks only when `NotebookLMGate` opens that persisted evidence file for notebook id `wwise-2022.1-docs`.

## Official/source URLs

- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_soundbank_generate.html
- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_soundbank_setinclusions.html
- https://www.audiokinetic.com/library/edge/?id=ak_wwise_core_soundbank_processdefinitionfiles.html
- https://www.audiokinetic.com/en/public-library/2025.1.5_9095/?id=ak_wwise_core_soundbank_setinclusions_example_adding_an_object_to_the_inclusion_list.html
- `resources/manifest/2022.1/schemas.json`
- NotebookLM notebook `wwise-2022.1-docs`, cited answer for SoundBank endpoints.

## Endpoint list

- `ak.wwise.core.soundbank.getInclusions`
- `ak.wwise.core.soundbank.setInclusions`
- `ak.wwise.core.soundbank.generate`
- `ak.wwise.core.soundbank.convertExternalSources`
- `ak.wwise.core.soundbank.processDefinitionFiles`
- `ak.wwise.core.soundbank.generated`
- `ak.wwise.core.soundbank.generationDone`

## Required fields

- `getInclusions`: `soundbank`.
- `generate`: no required fields unless `soundbanks` entries are supplied.
- `setInclusions`: `soundbank`, `operation`, `inclusions`.
- `convertExternalSources`: no required fields.
- `processDefinitionFiles`: `files` array.
- `generated` and `generationDone`: topic payload only.

## Optional fields

- `soundbanks` with name, events, auxBusses, inclusions, rebuild
- `platforms`
- `languages`
- `skipLanguages`
- `rebuildSoundBanks`
- `clearAudioFileCache`
- `writeToDisk`
- `rebuildInitBank`

## Return shape

`generate` returns a logs array; `setInclusions` returns an empty JSON object; `processDefinitionFiles` reports generation through WAAPI log output.

## Destructive behavior

Mutating. `clearAudioFileCache` deletes the audio file cache for all platforms; `setInclusions operation=replace` clears existing SoundBank inclusions.

## Ambiguity constraints

String object references must use `type:name` or `Global:shortId`; `generationDone` is not sufficient proof that generation fully completed.

## Unsupported cases

Do not include profiler, transport, soundengine, UI, CLI, remote, or debug APIs; do not treat `generationDone` as a completion gate.

## Cited required fields

- `ak.wwise.core.soundbank.getInclusions: soundbank`
- `ak.wwise.core.soundbank.generate: no required fields unless soundbanks entries are supplied`
- `ak.wwise.core.soundbank.setInclusions: soundbank, operation, inclusions`
- `ak.wwise.core.soundbank.processDefinitionFiles: files array`
- `ak.wwise.core.soundbank.convertExternalSources: no required fields`
- `ak.wwise.core.soundbank.generated: topic payload only`
- `ak.wwise.core.soundbank.generationDone: topic payload only`
