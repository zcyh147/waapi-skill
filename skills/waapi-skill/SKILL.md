---
name: waapi-skill
description: Use this skill for Wwise WAAPI automation through the skill-local Python runner, versioned manifests, semantic builders, bounded subscriptions, and safe dispatcher calls. Always use this skill when the task mentions Wwise, WAAPI, Audiokinetic APIs, generated manifests, topic subscriptions, Wwise version selection, or destructive Wwise guardrails.
---

# Wwise WAAPI Skill

Use this skill to automate Wwise through WAAPI with a Python-first workflow. The normal path is: make sure Python can run the skill-local wrapper, identify the target Wwise version, then use the dispatcher or semantic builders for the requested task.

Supported Wwise versions are `2021.1`, `2022.1`, `2023.1`, `2024.1`, and `2025.1`.

## Setup and runner

Use the skill-local wrapper so dependencies and paths are handled consistently:

```bash
python scripts/run.py --help
python scripts/run.py setup_environment.py
```

For task work, call the Python layer instead of inventing shell commands. The main pieces are:

1. `scripts/run.py`: runs skill-local helper scripts with the right import path.
2. `wwise_waapi.dispatcher`: validates WAAPI functions and topics against versioned manifests, then calls WAAPI or waits for bounded topic events.
3. `resources/manifest/<version>/`, `resources/semantic/<version>/`, `resources/waql/<version>/`, and `resources/deferred/<version>.json`: loaded on demand for the selected version and task. Semantic builders validate the packaged `source_notes.json` metadata for the selected version; root `references/` markdown remains repository development/source evidence and is not a packaged runtime dependency.
4. `wwise_waapi.builders`: semantic builders for common query, object mutation, import, soundbank, property, reference, and switch container tasks.

## Version selection

Prefer an explicit user-provided Wwise version when the task depends on exact API behavior. Pass one of `2021.1`, `2022.1`, `2023.1`, `2024.1`, or `2025.1` to the dispatcher or builder flow when known.

If the user does not specify a version, first probe the live Wwise connection with `ak.wwise.core.getInfo` through the runner or dispatcher, and also record the live WAAPI host/port that worked for this session. Infer the nearest supported version from the returned Wwise version when possible. If probing is unavailable or the version cannot be mapped safely, ask the user for the target version or use the documented fallback only for dry-run or low-risk read-only work.

Persist the approved version, WAAPI host, and WAAPI port in the skill-local JSON config at `data/config.json` so future runs do not depend on conversation memory. Agents should read that config first and only probe live state again when the connection needs to be verified or the saved values are missing.

The saved config is user-overridable. If the user chooses a different Wwise version or WAAPI port, update the config and keep using that saved override until the user changes it again.

By default, the config leaves `wwise_version` unset, uses `127.0.0.1` for the WAAPI host, and leaves the port unset so WAAPI can use its normal default.

Example dispatcher shape:

```python
from wwise_waapi import WwiseDispatcher

result = WwiseDispatcher(client=waapi_client).dispatch(
    "ak.wwise.core.getInfo",
    version="2025.1",
    args={},
    options={},
    timeout=10.0,
    dry_run=False,
    allow_destructive=False,
    evidence_dir=".sisyphus/evidence/waapi",
)
```

Topic waits use the same dispatcher rather than a separate topic skill:

```python
result = WwiseDispatcher(client=waapi_client).dispatch(
    "ak.wwise.core.object.created",
    version="2025.1",
    timeout=5.0,
    topic_mode="wait",
)
```

## Dispatch model

The dispatcher input is a small, explicit contract:

1. `api`: reflected WAAPI URI such as `ak.wwise.core.getInfo`.
2. `version`: manifest version, selected explicitly or inferred from `getInfo` when possible.
3. `args` and `options`: JSON-like mappings passed to function calls or topic subscriptions.
4. `timeout`: finite call or wait timeout. Prefer 5 to 10 seconds unless there is a clear reason to wait longer.
5. `dry_run`: validates and previews the action without calling WAAPI.
6. `allow_destructive`: per-call opt-in for mutating or destructive operations.
7. `evidence_dir`: optional location for structured JSON evidence.
8. `topic_mode`: use `wait` for bounded topic dispatch. Use `SubscriptionManager` directly only when the caller owns listener cleanup.

Every dispatcher result is structured and safe to log:

```json
{
  "ok": true,
  "api": "ak.wwise.core.getInfo",
  "version": "2025.1",
  "item_type": "function",
  "result": {},
  "error_code": null,
  "message": "ok",
  "evidence_path": null
}
```

Errors must stay structured with `ok`, `api`, `version`, `error_code`, `message`, and `evidence_path`. Do not replace dispatcher failures with vague prose.

## Semantic builders

For complex WAAPI work, prefer `wwise_waapi.builders` semantic builders before hand-writing dispatcher payloads. Builders construct and validate source-grounded envelopes, previews, readback plans, and dispatcher requests; they do not open Wwise, subscribe to topics, or dispatch live calls by default.

Use builders for these task families:

1. `query`: WAQL-backed `ak.wwise.core.object.get` previews.
2. `object-mutation`: create, set, delete, copy, move, diff, paste properties, and undo previews.
3. `property-reference`: property, reference, curve, randomizer metadata, and setter previews.
4. `import`: audio import, tab-delimited import, and import-topic evidence previews.
5. `soundbank`: inclusion, generation, external source, process definition, and topic evidence previews.
6. `switchcontainer`: assignment readback, guarded add or remove previews, and topic evidence expectations.

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

The raw `WwiseDispatcher` contract remains the explicit escape hatch for low-level WAAPI work or unsupported builder coverage. For unfamiliar calls, preview with `dry_run=True` first and keep timeouts bounded.

## Safety guardrails

Mutating and destructive operations are blocked by default. Only pass `allow_destructive=True` for a clearly requested change, after previewing when possible, and only against a project the user intentionally chose for that operation. Do not casually target a user's active production project.

Treat operations such as object deletion, object creation, property mutation, imports, soundbank changes, switch container assignment changes, and undo-group mutations as potentially destructive. Prefer read-only queries and dry runs until the requested edit is clear.

Keep runtime data, logs, auth state, and evidence artifacts out of git unless the user or plan explicitly asks for committed evidence. Do not claim Windows validation has passed unless the task provides real Windows-host evidence.

## Resources and documentation

The prompt should not load every reference file up front. Python code reads versioned manifests, semantic source notes, WAQL resources, and deferred registries for the selected version and task. The structured `resources/semantic/<version>/source_notes.json` files are the runtime semantic source-note resource; their `protocol`, `gate_evidence_path`, and `source_urls` fields are metadata pointing back to repository source-evidence history, not markdown files that packaged runtime validation opens.

Use NotebookLM-gated documentation only for documentation-sensitive source-note refresh or semantic behavior questions that cannot be answered from packaged resources. Runtime dispatcher and builder flows should rely on local packaged resources, not large prompt-loaded 2025 reference files.

## Skill layout

Key paths:

1. `scripts/run.py`: skill-local script runner.
2. `wwise_waapi/dispatcher.py`: generic WAAPI function and topic dispatcher.
3. `wwise_waapi/subscriptions.py`: bounded topic waits and cancellable listeners.
4. `wwise_waapi/manifest.py`: versioned manifest loading and reflection helpers.
5. `wwise_waapi/builders/`: semantic builders and preview objects.
6. `resources/manifest/<version>/`: generated API manifests.
7. `resources/semantic/<version>/`, `resources/waql/<version>/`, and `resources/deferred/<version>.json`: versioned runtime supporting resources loaded only when needed. Root `references/` and `references/semantic/<version>/` keep historical NotebookLM/source-evidence markdown for development review outside the packaged runtime path.
