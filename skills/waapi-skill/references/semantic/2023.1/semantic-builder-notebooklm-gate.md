# Semantic builder NotebookLM gate evidence for Wwise 2023.1

- Gate status: open
- Notebook id: wwise-2023.1-docs
- Auth result: success
- List result: success
- Query result: success
- Command: python scripts/run.py ask_question.py --question "For Wwise 2023.1 WAAPI semantic builder source notes, summarize only these families: query, object-mutation, property-reference, import, soundbank, switchcontainer. For each family, cite sources and list relevant official WAAPI URI endpoints, required fields, optional fields, return shape, destructive behavior, ambiguity constraints, unsupported cases, and official/source URLs if present. Include WAQL reference and object.get for query; object.create/object.set/delete/copy/move/diff/pasteProperties and undo group endpoints for object mutation; getTypes/getPropertyAndReferenceNames/getPropertyInfo/isPropertyEnabled/getAttenuationCurve/setName/setNotes/setProperty/setReference/setRandomizer/setAttenuationCurve for property/reference; audio.import/importTabDelimited/imported for import; soundbank getInclusions/setInclusions/generate/convertExternalSources/processDefinitionFiles/generated/generationDone for soundbank; switchContainer add/get/remove assignment and assignment topics for switchcontainer. Answer from sources only and keep it concise." --notebook-id wwise-2023.1-docs
- Evidence scope: versioned semantic builder source-note grounding for Wwise 2023.1 only.
- Evidence path: references/semantic/2023.1/semantic-builder-notebooklm-gate.md
- Local persistence: this file is the persisted local gate record. Runtime builders must read versioned local source-note resources later, not query NotebookLM at runtime.

## Source evidence status

- NotebookLM query status: source-grounded answer returned for notebook id `wwise-2023.1-docs`.
- Official URL status: evidence-candidate. The Audiokinetic public-library pages are recorded as official candidate URLs, but this task did not directly fetch and verify every page because those pages may require human verification.
- Citation caveat: NotebookLM returned numbered citations in the browser answer, not stable source URLs. The family notes persist cited required fields and official URL candidates separately.

## Official URL candidates

- https://blog.audiokinetic.com/waapi-for-wwise-2023.1/
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2023.1.19_8928/?id=waql_reference.html
