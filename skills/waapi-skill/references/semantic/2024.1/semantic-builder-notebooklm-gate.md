# Semantic builder NotebookLM gate evidence for Wwise 2024.1

- Gate status: open
- Notebook id: wwise-2024.1-docs
- Auth result: success
- List result: success
- Query result: success
- Command: python scripts/run.py auth_manager.py status
- Command: python scripts/run.py notebook_manager.py list
- Command: python scripts/run.py ask_question.py --question "For Wwise 2024.1 WAAPI semantic builder source notes, answer using only this notebook. For each family query, object-mutation, property-reference, import, soundbank, and switchcontainer, provide: endpoint inventory, required fields, optional fields, return shape, destructive behavior, ambiguity constraints, unsupported cases, cited required fields, and official Audiokinetic public-library URLs. Include citations from the Wwise 2024.1 docs and confirm notebook id wwise-2024.1-docs/version target 2024.1." --notebook-id wwise-2024.1-docs
- Command: python scripts/run.py ask_question.py --question "Using only notebook wwise-2024.1-docs for Wwise 2024.1, provide exact WAAPI required fields and return shapes for these endpoints and topics: ak.wwise.core.object.get, ak.wwise.core.object.create, set, delete, copy, move, diff, pasteProperties, ak.wwise.core.undo.beginGroup, endGroup, undo, ak.wwise.core.audio.import, importTabDelimited, imported, ak.wwise.core.soundbank.generate, getInclusions, setInclusions, convertExternalSources, processDefinitionFiles, generated, generationDone, ak.wwise.core.switchContainer.getAssignments, addAssignment, removeAssignment, assignmentAdded, assignmentRemoved. Include destructive behavior, unsupported cases, ambiguity constraints, and confirm version target 2024.1." --notebook-id wwise-2024.1-docs
- Command: python scripts/run.py ask_question.py --question "Using only notebook wwise-2024.1-docs for Wwise 2024.1, provide exact WAAPI required fields and return shapes for property/reference endpoints: ak.wwise.core.object.getTypes, getPropertyAndReferenceNames, getPropertyInfo, isPropertyEnabled, getAttenuationCurve, setName, setNotes, setProperty, setReference, setRandomizer, setAttenuationCurve, and isLinked if present. Include optional fields, destructive behavior, ambiguity constraints, unsupported cases, and cited required fields." --notebook-id wwise-2024.1-docs
- Evidence scope: versioned semantic builder source-note grounding for Wwise 2024.1 only.
- Evidence path: references/semantic/2024.1/semantic-builder-notebooklm-gate.md
- Local persistence: this file is the persisted local gate record. Runtime builders must read versioned local source-note resources later, not query NotebookLM at runtime.

## Source evidence status

- NotebookLM query status: source-grounded answers returned for notebook id `wwise-2024.1-docs`.
- Notebook list status: the listed exact identifier was `wwise-2024.1-docs` under Wwise 2024.1 Docs.
- Official URL status: evidence-candidate. The Audiokinetic public-library pages are recorded as official candidate URLs, but this task did not directly fetch and verify every page because those pages may require human verification.
- Citation caveat: NotebookLM returned numbered citations in the browser answer, not stable source URLs. The family notes persist cited required fields and official URL candidates separately.

## Official URL candidates

- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=waql_reference.html
- https://www.audiokinetic.com/en/public-library/2024.1.13_9056/?id=ak_wwise_core_object_get.html
