# Semantic builder NotebookLM gate evidence for Wwise 2025.1

- Gate status: open
- Notebook id: wwise-2025.1-docs
- Auth result: success
- List result: success
- Query result: success
- Command: python scripts/run.py auth_manager.py status
- Command: python scripts/run.py notebook_manager.py list
- Command: python scripts/run.py ask_question.py --question "For Wwise 2025.1 WAAPI semantic builder source notes, answer using only notebook wwise-2025.1-docs. Confirm notebook id wwise-2025.1-docs and version target 2025.1. For families query, object-mutation, property-reference, import, soundbank, and switchcontainer, provide endpoint inventory, required fields, optional fields, return shape, destructive behavior, ambiguity constraints, unsupported cases, cited required fields, official Audiokinetic public-library URL candidates, and citation/source labels. Include Wwise Authoring API Reference, Wwise Objects Reference, WAQL Reference, Command Identifiers, View Identifiers, Performance Monitor Counter Identifiers, and public endpoint/topic pages if present." --notebook-id wwise-2025.1-docs
- Command: python scripts/run.py ask_question.py --question "Using only notebook wwise-2025.1-docs for Wwise 2025.1, provide exact WAAPI required fields, optional fields, return shapes, destructive behavior, ambiguity constraints, unsupported cases, and official public-library URL candidate ids for query and object mutation endpoints only." --notebook-id wwise-2025.1-docs
- Command: python scripts/run.py ask_question.py --question "Using only notebook wwise-2025.1-docs for Wwise 2025.1, provide exact WAAPI required fields, optional fields, return shapes, destructive behavior, ambiguity constraints, unsupported cases, and official public-library URL candidate ids for property/reference endpoints." --notebook-id wwise-2025.1-docs
- Command: python scripts/run.py ask_question.py --question "Using only notebook wwise-2025.1-docs for Wwise 2025.1, provide exact WAAPI required fields, optional fields, return shapes, destructive behavior, ambiguity constraints, unsupported cases, and official public-library URL candidate ids for import, soundbank, and switchcontainer endpoint groups." --notebook-id wwise-2025.1-docs
- Evidence scope: versioned semantic builder source-note grounding for Wwise 2025.1 only.
- Evidence path: references/semantic/2025.1/semantic-builder-notebooklm-gate.md
- Local persistence: this file is the persisted local gate record. Runtime builders must read versioned local source-note resources later, not query NotebookLM at runtime.

## Source evidence status

- NotebookLM query status: source-grounded answers returned for notebook id `wwise-2025.1-docs`.
- Notebook list status: the listed exact identifier was `wwise-2025.1-docs` under Wwise 2025.1 Docs.
- Official URL status: evidence-candidate. NotebookLM confirmed exact public-library URL prefixes and page ids were not present in the notebook answer, so URL paths are recorded as candidates.
- Citation caveat: NotebookLM returned numbered citation labels in the browser answer, not stable source URLs. The family notes persist cited required fields and official URL candidates separately.

## Official URL candidates

- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi_functions_index.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waapi_topics_index.html
- https://www.audiokinetic.com/en/public-library/2025.1.7_6590/?id=waql_reference.html
