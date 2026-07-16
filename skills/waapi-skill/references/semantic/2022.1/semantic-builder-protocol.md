# Semantic builder source-note protocol

Version target: `2022.1`

NotebookLM notebook id: `wwise-2022.1-docs`

Semantic builder families are limited to exactly:

- `query`
- `object-mutation`
- `property-reference`
- `import`
- `soundbank`
- `switchcontainer`

Excluded families: profiler, transport, soundengine, UI, CLI, remote, and debug.

## Unlock rule

Each family source note must declare `status: grounded` or `status: fail-closed`. Only `status: grounded` unlocks a semantic builder. Missing notes, wrong NotebookLM notebook id, incomplete fields, duplicate endpoint URIs, or uncited required fields fail closed with typed semantic source-note errors.

## Required source-note fields

Each source note records:

- NotebookLM gate evidence path: every grounded note must point to one persisted evidence file that is checked with `wwise_waapi.notebooklm_gate.NotebookLMGate`.
- Official/source URLs.
- Endpoint list.
- Required fields.
- Optional fields.
- Return shape.
- Destructive behavior.
- Ambiguity constraints.
- Version target.
- Unsupported cases.
- Cited required fields.

The deterministic resource used by tests and future builders is `resources/semantic/2022.1/source_notes.json`. Markdown notes mirror that resource for human review.

Persisted gate evidence for this source-note set is `references/semantic/2022.1/semantic-builder-notebooklm-gate.md`. Do not copy `Auth result`, `List result`, or `Query result` claims into individual notes; the checker must read the evidence file and fail closed through `NotebookLMGate`.
