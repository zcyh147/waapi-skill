---
name: wwise-waapi
description: Use this skill for Wwise WAAPI automation, dispatcher calls, generated WAAPI manifests, bounded subscriptions, NotebookLM-gated Wwise documentation lookup, headless Wwise lifecycle work, or tests under `.agents/skills/wwise-waapi/`. Always use this skill when the task mentions Wwise, WAAPI, Audiokinetic APIs, generated manifests, topic subscriptions, destructive Wwise guardrails, or this repo's Wwise skill package; it provides the generic dispatcher contract and safety rules instead of one skill per API.
---

# Wwise WAAPI Skill

This skill provides one generic, manifest-backed WAAPI dispatcher for Wwise 2022.1 automation. Do not create one skill or wrapper per API: validate the requested URI against `resources/manifest/<version>/`, then dispatch functions through the WAAPI client or topics through the bounded subscription runtime.

## Command templates

Use the skill-local wrapper for scripts so the local environment and dependencies are managed consistently:

```bash
python .agents/skills/wwise-waapi/scripts/run.py --help
python .agents/skills/wwise-waapi/scripts/run.py setup_environment.py
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

Topic waits use the same dispatcher, not a separate topic-specific skill:

```python
result = WwiseDispatcher(client=waapi_client).dispatch(
    "ak.wwise.core.object.created",
    timeout=5.0,
    topic_mode="wait",
)
```

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
- Do not mutate user Wwise projects in unit tests. Use injectable fake clients for dispatcher and subscription tests.
- Keep runtime data, logs, auth state, and evidence artifacts out of git unless the plan explicitly asks for committed evidence.

## NotebookLM documentation gate

Documentation-sensitive generation must use the NotebookLM gate before relying on semantic Wwise API behavior. The accepted gate evidence must show `Gate status: open`, notebook id `wwise-2022.1-docs`, and successful auth/list/query checks. If the gate is missing or fail-closed, stop docs-dependent generation and request fresh NotebookLM evidence rather than guessing.

## Layout

- `wwise_waapi/dispatcher.py` - generic WAAPI function/topic dispatcher.
- `wwise_waapi/subscriptions.py` - bounded topic waits and cancellable listeners.
- `wwise_waapi/manifest.py` - generated manifest loading and reflection helpers.
- `wwise_waapi/deferred_registry.py` and `api_coverage_audit.py` - evidence-backed behavioral coverage deferrals.
- `wwise_waapi/headless.py` - headless lifecycle launch/probe/cleanup helpers for WwiseConsole WAAPI gates.
- `scripts/run.py` - thin command wrapper.
- `tests/unit/` - fast fake-client tests; live and destructive tests remain opt-in.
