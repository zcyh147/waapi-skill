# Semantic builder source-note protocol for Wwise 2024.1

Version target: `2024.1`

NotebookLM notebook id: `wwise-2024.1-docs`

Persisted gate evidence: `references/semantic/2024.1/semantic-builder-notebooklm-gate.md`

Semantic builder families are limited to exactly:

- `query`
- `object-mutation`
- `property-reference`
- `import`
- `soundbank`
- `switchcontainer`

Excluded families: profiler, transport, soundengine, UI, CLI, remote, and debug.

## Unlock rule

Each 2024.1 family note must point to the versioned local gate evidence file above and must never point to 2022.1 or 2023.1 semantic notes, global semantic-builder references, or non-2024 paths as proof. Missing local evidence, wrong NotebookLM notebook id, incomplete endpoint inventory, duplicate endpoint URIs, or uncited required fields must fail closed when later tasks create runtime resources.

## Required source-note fields

Each family note records:

- NotebookLM gate evidence path.
- Notebook id.
- Version target.
- Official/source URLs.
- Endpoint inventory.
- Required fields.
- Optional fields.
- Return shape.
- Destructive behavior.
- Ambiguity constraints.
- Unsupported cases.
- Cited required fields.
- Evidence caveat for source URLs that could not be directly fetched in this environment.

The future deterministic resource for tests and builders is expected at `resources/semantic/2024.1/source_notes.json`. Markdown notes in this folder are the human reference layout only. Runtime builders must read local JSON and Markdown resources, not NotebookLM.
