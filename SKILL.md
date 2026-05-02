---
name: wwise-waapi
description: Use this skill for Wwise WAAPI automation, dispatcher calls, generated WAAPI manifests, bounded subscriptions, NotebookLM-gated Wwise documentation lookup, headless Wwise lifecycle work, or tests in this root-level skill repository. Always use this skill when the task mentions Wwise, WAAPI, Audiokinetic APIs, generated manifests, topic subscriptions, destructive Wwise guardrails, or this repo's Wwise skill package; it provides the generic dispatcher contract and safety rules instead of one skill per API.
---

# Wwise WAAPI Skill

This skill provides one generic, manifest-backed WAAPI dispatcher for Wwise automation. The default behavior remains Wwise 2022.1. Wwise 2021.1 is supported only where versioned manifests, semantic source notes, tests, and evidence resources exist. Wwise 2023.1, 2024.1, and 2025.1 are supported only where versioned manifests, semantic source notes, tests, and evidence resources exist. Do not create one skill or wrapper per API: validate the requested URI against `resources/manifest/<version>/`, then dispatch functions through the WAAPI client or topics through the bounded subscription runtime.

## Command templates

Use the skill-local wrapper for scripts so the local environment and dependencies are managed consistently:

```bash
python scripts/run.py --help
python scripts/run.py setup_environment.py
```

Python callers should use the dispatcher shape below:

```python
from wwise_waapi import WwiseDispatcher

result = WwiseDispatcher(client=waapi_client).dispatch(
    "ak.wwise.core.getInfo",
    args={},
    options={},
    timeout=10.0,
    dry_run=False,
    allow_destructive=False,
    evidence_dir=".sisyphus/evidence/waapi",
)
```

Wwise 2021.1 live gates must use explicit version and path inputs. Use these exact local command templates only for opt-in 2021.1 validation, never for default pytest. The installed SampleProject is immutable source only; destructive tests must copy it into `WWISE_SANDBOX_ROOT` and may mutate only the copied sandbox:

```bash
WWISE_VERSION=2021.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" \
WWISE_LIVE=1 \
python -m pytest tests/live/test_2021_1_live_prerequisites.py tests/live/test_2021_1_reflection_prerequisites.py tests/live/test_2021_1_object_get_matrix.py -q

WWISE_VERSION=2021.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive/test_2021_1_project_mutation_sandbox.py tests/destructive/test_2021_1_soundbank_audio_sandbox.py tests/destructive/test_2021_1_switchcontainer_assignment_sandbox.py -q
```

Wwise 2023.1 live gates must use explicit version and path inputs. Use these exact local command templates only for opt-in live or destructive validation, never for default pytest:

```bash
WWISE_VERSION=2023.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" \
WWISE_LIVE=1 \
python -m pytest tests/live -q

WWISE_VERSION=2023.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive -q
```

Wwise 2024.1 live gates also require exact version and path inputs. Use these templates only for opt-in 2024.1 validation, never for default pytest:

```bash
WWISE_VERSION=2024.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" \
WWISE_LIVE=1 \
python -m pytest tests/live/test_2024_live_prerequisites.py tests/live/test_2024_reflection_inventory.py tests/live/test_2024_waql_live_matrix.py -q

WWISE_VERSION=2024.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive/test_2024_project_mutation_sandbox.py tests/destructive/test_2024_soundbank_audio_sandbox.py tests/destructive/test_2024_switchcontainer_assignment_sandbox.py -q
```

Wwise 2025.1 live gates also require exact version and path inputs. Use these templates only for opt-in 2025.1 validation, never for default pytest:

```bash
WWISE_VERSION=2025.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" \
WWISE_READINESS_TIMEOUT=180 \
WWISE_LIVE=1 \
python -m pytest tests/live/test_2025_1_live_prerequisites.py tests/live/test_2025_1_reflection_inventory.py tests/live/test_2025_1_waql_live_matrix.py -q

WWISE_VERSION=2025.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes \
WWISE_READINESS_TIMEOUT=180 \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive/test_2025_1_project_mutation_sandbox.py tests/destructive/test_2025_1_soundbank_audio_sandbox.py tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py -q
```

Topic waits use the same dispatcher, not a separate topic-specific skill:

```python
result = WwiseDispatcher(client=waapi_client).dispatch(
    "ak.wwise.core.object.created",
    timeout=5.0,
    topic_mode="wait",
)
```


## Semantic builder APIs

For P0/P1/P2 complex WAAPI work, prefer `wwise_waapi.builders` semantic builders before writing raw dispatcher payloads. Builders construct and validate source-grounded envelopes, readback plans, and safe previews; they do not open Wwise, subscribe to topics, or dispatch live calls by default.

Use semantic builders for these grounded families:

- `query`: WAQL `ak.wwise.core.object.get` previews.
- `object-mutation`: `object.create`, `object.set`, `object.delete`, copy/move/diff/pasteProperties, and undo previews.
- `property-reference`: property/reference/curve/randomizer metadata and setter previews.
- `import`: audio import, tab-delimited import, and imported-topic evidence previews.
- `soundbank`: inclusion, generation, external-source, processDefinitionFiles, and topic evidence previews.
- `switchcontainer`: assignment readback, guarded add/remove previews, and topic evidence expectations.

Example preview pattern:

```python
from wwise_waapi.builders import QueryPredicate, build_object_get_query

preview = build_object_get_query(
    type="Sound",
    where=QueryPredicate("@Volume", "<", 0),
    return_fields=("id", "name", "path", "type", "@Volume"),
)
payload = preview.dispatch_payload()
request = preview.to_dispatcher_request()
```

The raw `WwiseDispatcher` contract remains the explicit escape hatch for unsupported or low-level WAAPI work. When using that escape hatch, keep `dry_run=True` first for unfamiliar calls, set finite timeouts, and pass destructive opt-in only for isolated fixture or sandbox projects.

## Dispatcher input contract

- `api` (required): reflected WAAPI URI such as `ak.wwise.core.getInfo`.
- `version`: manifest version, default `2022.1`.
- `args` / `options`: JSON-like mappings passed to WAAPI function calls or topic subscription options.
- `timeout`: bounded wait/call timeout in seconds; prefer 5-10 seconds for unit/integration work and only raise it with a clear reason.
- `dry_run`: returns the validated action without calling WAAPI; use this before risky or unfamiliar calls.
- `allow_destructive`: explicit per-call opt-in for mutating operations. The environment variable `WWISE_DESTRUCTIVE=1` is the only global opt-in.
- `evidence_dir`: optional directory for a JSON evidence file. When set, every success or error includes `evidence_path` pointing to the written file.
- `topic_mode`: `wait` for bounded topic dispatch. Long-running listeners should use `SubscriptionManager` directly so cleanup ownership is explicit.

## Dispatcher output contract

Every dispatcher result is a dictionary that can be logged as evidence.

Success:

```json
{
  "ok": true,
  "api": "ak.wwise.core.getInfo",
  "version": "2022.1",
  "item_type": "function",
  "result": {},
  "error_code": null,
  "message": "ok",
  "evidence_path": null
}
```

Error results are also structured and must not be replaced with vague prose:

```json
{
  "ok": false,
  "api": "ak.wwise.core.object.delete",
  "version": "2022.1",
  "error_code": "DESTRUCTIVE_BLOCKED",
  "message": "Destructive WAAPI calls are blocked unless allow_destructive=True or WWISE_DESTRUCTIVE=1 is set",
  "evidence_path": ".sisyphus/evidence/waapi/...json"
}
```

Required error fields are `ok`, `api`, `version`, `error_code`, `message`, and `evidence_path`.

## Safety guardrails

- Generated manifests are authoritative for API existence and for distinguishing functions from topics.
- Destructive or mutating functions are blocked by default. Use `dry_run=True` first, then pass `allow_destructive=True` only for fixture projects or intentionally destructive test gates.
- Default pytest collection skips `live` and `destructive` tests unless `WWISE_LIVE=1` and `WWISE_DESTRUCTIVE=1` are present.
- Phase 2 live tests use the canonical environment contract in `wwise_waapi.live_environment`: `WWISE_SAMPLE_PROJECT_PATH` is the immutable source-to-copy (defaulting to `/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject` only when that path exists), `WWISE_FIXTURE_PROJECT` is read-only for live smoke, and destructive tests may only mutate a fixture project under `WWISE_SANDBOX_ROOT` with both `WWISE_LIVE=1` and `WWISE_DESTRUCTIVE=1`.
- Do not mutate user Wwise projects in unit tests. Use injectable fake clients for dispatcher and subscription tests.
- Keep runtime data, logs, auth state, and evidence artifacts out of git unless the plan explicitly asks for committed evidence.

## NotebookLM documentation gate

Documentation-sensitive source-note generation or refresh must use the NotebookLM gate before relying on semantic Wwise API behavior. Runtime builders and dispatcher flows do not query NotebookLM. Runtime reads local persisted evidence and source notes only.

- Wwise 2021.1 source notes use notebook id `wwise-2021.1.14-docs`, versioned references under `references/semantic/2021.1/`, and local source-note resource `resources/semantic/2021.1/source_notes.json`. These notes are source-only and are not runtime or behavior proof.
- Wwise 2022.1 source notes use notebook id `wwise-2022.1-docs` and persisted evidence such as `references/semantic-builder-notebooklm-gate.md`.
- Wwise 2023.1 source notes use notebook id `wwise-2023.1-docs`, versioned references under `references/semantic/2023.1/`, and local source-note resource `resources/semantic/2023.1/source_notes.json`.
- Wwise 2024.1 source notes use notebook id `wwise-2024.1-docs`, versioned references under `references/semantic/2024.1/`, and local source-note resource `resources/semantic/2024.1/source_notes.json`.
- Wwise 2025.1 source notes use notebook id `wwise-2025.1-docs`, versioned references under `references/semantic/2025.1/`, and local source-note resource `resources/semantic/2025.1/source_notes.json`.
- If the gate evidence is missing, wrong, or fail-closed for the requested version, stop docs-dependent source-note refresh and request fresh NotebookLM evidence rather than guessing.

## Version support scope

- `2022.1` remains the default dispatcher, live environment, semantic source-note, and docs behavior.
- `2021.1` is explicit opt-in support. It has reflected inventory and parity classification for 99 functions, backed by `resources/manifest/2021.1/`, `resources/semantic/2021.1/source_notes.json`, `resources/coverage/2021.1/`, `resources/deferred/2021.1.json`, `resources/waql/2021.1/`, and `references/semantic/2021.1/`. Behavioral evidence is limited to one live read-only URI, `ak.wwise.core.object.get`, and nine copied-sandbox mutating URIs: `ak.wwise.core.audio.import`, `ak.wwise.core.object.create`, `ak.wwise.core.object.delete`, `ak.wwise.core.object.setNotes`, `ak.wwise.core.soundbank.setInclusions`, `ak.wwise.core.switchContainer.addAssignment`, `ak.wwise.core.switchContainer.removeAssignment`, `ak.wwise.core.undo.beginGroup`, and `ak.wwise.core.undo.endGroup`. The remaining entries are 43 deferred and 46 excluded, with supported 0, behavioral 0, and unknown 0. The installed SampleProject path is immutable source only; destructive tests require copied sandboxes under `.sisyphus/runtime/wwise-waapi-sandboxes`. NotebookLM and source notes are source-only, not runtime proof, and readback or setup helpers such as `ak.wwise.core.soundbank.getInclusions`, `ak.wwise.core.switchContainer.getAssignments`, and `ak.wwise.core.object.setReference` remain unpromoted.
- `2023.1` is explicit opt-in support. It is supported only where the repo has versioned resources, source notes, tests, and evidence under paths such as `resources/manifest/2023.1/`, `resources/semantic/2023.1/source_notes.json`, `resources/coverage/2023.1/`, and `references/semantic/2023.1/`.
- The 2023.1 coverage model separates `supported`, `deferred`, `excluded`, `untested`, `evidence-only`, and reserved `live-tested`. Manifest reflection, skipped live tests, and skipped destructive tests are not behavioral proof.
- `2024.1` is explicit opt-in support. It has complete reflected inventory and parity classification for 148 functions, backed by `resources/manifest/2024.1/`, `resources/semantic/2024.1/source_notes.json`, `resources/coverage/2024.1/`, `resources/deferred/2024.1.json`, `resources/waql/2024.1/`, and `references/semantic/2024.1/`. Behavioral evidence is limited to one live read-only URI, `ak.wwise.core.object.get`, and ten copied-sandbox mutating URIs: `ak.wwise.core.audio.import`, `ak.wwise.core.object.create`, `ak.wwise.core.object.delete`, `ak.wwise.core.object.set`, `ak.wwise.core.soundbank.setInclusions`, `ak.wwise.core.switchContainer.addAssignment`, `ak.wwise.core.switchContainer.removeAssignment`, `ak.wwise.core.undo.beginGroup`, `ak.wwise.core.undo.endGroup`, and `ak.wwise.core.undo.undo`. The remaining 137 entries are deferred or excluded. Readback helpers such as `ak.wwise.core.soundbank.getInclusions` and `ak.wwise.core.switchContainer.getAssignments` remain unpromoted.
- `2025.1` is explicit opt-in support. It has complete reflected inventory and parity classification for 154 functions, backed by `resources/manifest/2025.1/`, `resources/semantic/2025.1/source_notes.json`, `resources/coverage/2025.1/`, `resources/deferred/2025.1.json`, `resources/waql/2025.1/`, and `references/semantic/2025.1/`. Behavioral evidence is limited to one live read-only URI, `ak.wwise.core.object.get`, and ten copied-sandbox mutating URIs: `ak.wwise.core.audio.import`, `ak.wwise.core.object.create`, `ak.wwise.core.object.delete`, `ak.wwise.core.object.set`, `ak.wwise.core.soundbank.setInclusions`, `ak.wwise.core.switchContainer.addAssignment`, `ak.wwise.core.switchContainer.removeAssignment`, `ak.wwise.core.undo.beginGroup`, `ak.wwise.core.undo.endGroup`, and `ak.wwise.core.undo.undo`. The remaining 143 entries are deferred or excluded, split as 95 deferred and 48 excluded. 2024 evidence is comparison metadata only, skipped live or destructive tests are not behavior proof, NotebookLM-only text is not runtime proof, and Windows validation remains a caveat and follow-up rather than macOS validation.

## Layout

- `wwise_waapi/dispatcher.py` - generic WAAPI function/topic dispatcher.
- `wwise_waapi/subscriptions.py` - bounded topic waits and cancellable listeners.
- `wwise_waapi/manifest.py` - generated manifest loading and reflection helpers.
- `wwise_waapi/deferred_registry.py` and `api_coverage_audit.py` - evidence-backed behavioral coverage deferrals.
- `wwise_waapi/headless.py` - headless lifecycle launch/probe/cleanup helpers for WwiseConsole WAAPI gates.
- `resources/semantic/2021.1/source_notes.json`, `resources/coverage/2021.1/`, `resources/deferred/2021.1.json`, `resources/waql/2021.1/`, and `references/semantic/2021.1/` - versioned 2021.1 inventory, semantic, source-only NotebookLM notes, live read-only, destructive sandbox, and parity audit resources.
- `resources/semantic/2023.1/source_notes.json` and `references/semantic/2023.1/` - versioned 2023.1 semantic source-note resources and audit references.
- `resources/semantic/2024.1/source_notes.json`, `resources/coverage/2024.1/`, `resources/deferred/2024.1.json`, `resources/waql/2024.1/`, and `references/semantic/2024.1/` - versioned 2024.1 inventory, semantic, coverage, live read-only, and parity audit resources.
- `resources/semantic/2025.1/source_notes.json`, `resources/coverage/2025.1/`, `resources/deferred/2025.1.json`, `resources/waql/2025.1/`, and `references/semantic/2025.1/` - versioned 2025.1 inventory, semantic, coverage, live read-only, destructive sandbox, and parity audit resources.
- `scripts/run.py` - thin command wrapper.
- `tests/unit/` - fast fake-client tests; live and destructive tests remain opt-in.
