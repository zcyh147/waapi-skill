---
name: waapi-skill
description: Use this skill for Wwise WAAPI automation through the skill-local Python runner, versioned manifests, semantic builders, bounded subscriptions, and safe dispatcher calls. Always use this skill when the task mentions Wwise, WAAPI, Audiokinetic APIs, generated manifests, topic subscriptions, Wwise version selection, or destructive Wwise guardrails.
---

# Wwise WAAPI Skill

Use this skill to automate Wwise through WAAPI with a Python-first workflow. The normal path is: make sure Python can run the skill-local wrapper, identify the target Wwise version, then extract a structured semantic intent and route it through the semantic planner.

When config and live WAAPI connection details are already known, execute the live read-only query first for ordinary inspection requests. Here, direct means direct through the skill-local runner and manifest-backed `WwiseDispatcher`, not hand-written one-off `WaapiClient.call(...)` business logic. Do not start by inspecting repository files or launching documentation research unless the user explicitly asked for investigation or the direct connection path is blocked.

## Welcome/status UX for Wwise version detection

For simple user-facing questions such as "which Wwise version is open?", "what project is currently open?", or any first action that needs to choose the matching WAAPI version, treat the first visible reply as the skill's welcome surface. Start with the skill, connection endpoint, and version-detection purpose, not with a generic safety preamble or developer-facing reasoning. This improves UX because the user immediately sees that the Wwise-specific skill is active, which endpoint is being checked, and why version detection matters before any WAAPI work continues.

Use this sequence:

1. Immediately tell the user that `waapi-skill` is loaded and state the host/port you will try first to detect the current Wwise version and choose the compatible WAAPI support version. Use the saved `data/config.json` host/port when present; otherwise say the default WAAPI endpoint such as `127.0.0.1:8080`. Example: `waapi-skill is loaded. I will use 127.0.0.1:8080 to detect the current Wwise version so I can select the compatible WAAPI support version.`
2. Connect to Wwise with `ak.wwise.core.getInfo`. If the saved config already has a host, port, and version, name each value clearly before connecting. Example: `The saved config has WAAPI endpoint 127.0.0.1:8080 and the previously recorded Wwise version 2022.1. I will connect to Wwise now to confirm the correct configuration.` If the saved port fails and no user-provided port was required, try the normal WAAPI default/fallback candidates before giving up, and report the port that actually worked.
3. On success, report: `Found Wwise on <host>:<port>; the detected version is <display/version>. I updated the config active Wwise version to <supported-version>.` Then answer the user's actual question, adding project details from `ak.wwise.core.getProjectInfo` when needed.
4. On failure to detect any connectable Wwise endpoint, stop the WAAPI request path and say directly: `No running Wwise instance with a connectable WAAPI endpoint was detected, so this request cannot continue.` Include the tried host/ports briefly, but do not answer from saved config or process-path guesses as if they were the current connected Wwise state.
5. Avoid opening with phrases like `This is a read-only query...`, `I will directly call WAAPI...this will not modify the project`, `live WAAPI`, `old config`, or `current project fact`. Safety can be mentioned later only if it helps explain a mutation guardrail; for welcome UX, users first need to know which skill, endpoint, detected version, and config update state are active.

Supported Wwise versions are `2021.1`, `2022.1`, `2023.1`, `2024.1`, and `2025.1`.

## Operator protocol

Use this closed semantic-intent protocol before choosing scripts, builders, manifests, or docs. Extract one structured `SemanticIntent`, call `SemanticPlanner.plan()`, present the resulting `SemanticPlan` preview, require confirmation for project-changing steps, execute only when the submitted preview hash exactly matches `SemanticPlan.preview_hash`, then verify with the plan's verification steps. Do not invent intent families.

```python
from wwise_waapi.semantic_planner import SemanticIntent, SemanticIntentTarget, SemanticPlanner, confirm_semantic_plan

intent = SemanticIntent(...)
plan = SemanticPlanner().plan(intent)
verification_steps = list(plan.verification_steps)
facts = {
    "structured_intent_extracted": True,
    "semantic_family": intent.family,
    "semantic_planner_invoked": True,
    "semantic_plan_status": str(plan.status),
    "preview_hash": plan.preview_hash,
    "source_builder_refs": list(plan.source_builder_refs),
    "unsupported_boundary_returned": plan.unsupported_capability,
    "unsupported_boundary_reason": plan.blocked_reason,
    "mutation_executed": False,
    "mutation_executed_before_confirmation": False,
    "verification_status": "not_applicable_unsupported_boundary" if plan.unsupported_capability else "planned",
}
submitted_preview_hash = confirmation_response.preview_hash
confirmed = confirm_semantic_plan(
    plan,
    confirmation_state=confirmation_response.state,
    submitted_preview_hash=submitted_preview_hash,
)
```

1. Extract `SemanticIntent` with one family: `intent_navigation`, `crud_authoring`, `system_design_preview`, `asset_import_workflow`, `soundbank_workflow`, `switch_assignment_workflow`, `bounded_profiler_guidance`, or `unsupported_runtime_boundary`.
2. Even read-only navigation and unsupported boundary requests still pass through `SemanticPlanner.plan()`. If persisted config and a currently connectable WAAPI session are available, live WAAPI may supplement or verify the plan, but it does not replace planner facts. Use repository or documentation research only when the user explicitly asks for it or direct execution is blocked, and report the blocker.
3. Route CRUD requests at the semantic family level: object creation, object mutation, property/reference edits, copy/move/delete, imports, soundbanks, and switch assignments become structured intent details for the planner. Do not paste raw WAAPI payload schemas into the prompt.
4. Present the `SemanticPlan` preview before project-changing work. Include family, step summaries, target identities, risk flags, verification plan, and `preview_hash`; do not execute from prose-only confirmation.
5. Confirm with `confirm_semantic_plan(preview, confirmation_state, submitted_preview_hash)`, where `submitted_preview_hash` is read from the user's confirmation response, not copied from the preview object by construction. Continue only when `confirmation_state` is `confirmed` and `submitted_preview_hash` exactly matches the current preview hash. Missing or mismatched hashes require a fresh preview.
6. Execute only the confirmed plan whose hash matched the preview shown to the user. If target identity, planned API, options, arguments, payload preview, or risk flags drift, abort and re-preview.
7. Verify after execution using the plan's readback, bounded topic evidence, or other verification templates. Semantic capability runs must emit one machine-readable `SEMANTIC_RESULT_JSON` object with at least `structured_intent_extracted`, `semantic_family`, `semantic_planner_invoked`, `semantic_plan_status`, `preview_hash` when present or required, `source_builder_refs`, `unsupported_boundary_returned`, `unsupported_boundary_reason`, `mutation_executed`, `mutation_executed_before_confirmation`, and `verification_status`. Report structured failures rather than replacing them with vague prose.

Unsupported boundary requests: scheduler or delayed runtime posting, Game Object View emitter control, timed runtime or ambience playback, audio narrative sequencing, RTPC ramps over time, and cross-app MCP federation are not supported execution capabilities. Route them as `unsupported_runtime_boundary`; these plans have no execution steps, no preview id or hash, and no verification claims. Offer supported alternatives only when appropriate, such as authoring a static object or switch plan, previewing soundbank changes, or running a live read summary.

Named invariant: Preview hash invariant. The preview-resolved target identity and preview artifact must be reused during confirmed execution. If confirmed execution cannot prove it is using the same `SemanticPlan.preview_hash`, abort and re-preview.

Protocol config boundary: saved public config fields are exactly `wwise_version`, `waapi_host`, `waapi_port`, and `project_modification_policy`. startup timeouts, readiness timeouts, default `WwiseConsole` paths, environment variables, scaffold directories, and legacy internal flags such as `use_current_selection_for_ambiguous_queries` are runtime or implementation details, not saved public config.

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

## Read-only inspection scaffolding

Ordinary inspection tasks such as current Wwise version, current project info, current selection, object lookup, or hierarchy browsing should reuse the skill scaffolding. After the welcome/status line, analyze the user's intent, select the supported semantic family when one applies, and load the versioned runtime resources needed for that intent: `resources/semantic/<version>/source_notes.json`, `resources/waql/<version>/`, `resources/deferred/<version>.json`, and `resources/manifest/<version>/`. A short connection harness is acceptable when needed, but API selection, args, options, timeout, version, and evidence handling must come from those resources and route through `WwiseDispatcher` or an existing semantic builder. Do not generate disposable business logic that calls `WaapiClient.call(...)` directly for common inspection requests.

Do not hard-code a fixed API map in this skill prompt. For current selection questions such as "what object is selected?", resolve the selection capability from the detected version's manifest and deferred resources before choosing a WAAPI URI. Keep return fields explicit when a resource-backed request is selected, but pass them as dispatcher `options`, not as raw positional arguments to `WaapiClient.call`.

Use this pattern for read-only inspection work:

1. Load `data/config.json` for `wwise_version`, `waapi_host`, and `waapi_port`; verify the connection if needed.
2. Extract the user's inspection intent and choose the semantic family/resource path before choosing a WAAPI URI.
3. Load only the versioned semantic, WAQL, deferred, and manifest resources needed for that intent.
4. Create the WAAPI client only as the transport layer.
5. Dispatch the resource-selected operation through `WwiseDispatcher(client=client).dispatch(...)` with the detected or configured version.
6. Report the structured dispatcher result or a clear blocker. If the dispatcher cannot cover the resource-selected URI because the manifest lacks it for the selected version, say so and only then use a minimal raw WAAPI escape hatch.

If an escape hatch is required, state it explicitly in the final answer: `The skill dispatcher did not cover <uri> for <version>, so I used a minimal raw WAAPI fallback.` Do not present raw fallback code as the normal skill workflow.

## Version selection

Prefer an explicit user-provided Wwise version when the task depends on exact API behavior. Pass one of `2021.1`, `2022.1`, `2023.1`, `2024.1`, or `2025.1` to the dispatcher or builder flow when known.

If the user does not specify a version, first connect to the currently running Wwise instance with `ak.wwise.core.getInfo` through the runner or dispatcher, and also record the WAAPI host/port that worked for this session. Infer the nearest supported version from the returned Wwise version when possible. If detection is unavailable or the version cannot be mapped safely, ask the user for the target version or use the documented fallback only for dry-run or low-risk read-only work.

Persist the approved version, WAAPI host, and WAAPI port in the skill-local JSON config at `data/config.json` so future runs do not depend on conversation memory. Agents should read that config first and only reconnect to Wwise when the connection needs to be verified or the saved values are missing.

The saved config is user-overridable. The stable persisted user-facing config surface is limited to `wwise_version`, `waapi_host`, `waapi_port`, and `project_modification_policy`. If the user chooses a different Wwise version or WAAPI port, update the config and keep using that saved override until the user changes it again.

By default, the config leaves `wwise_version` unset, uses `127.0.0.1` for the WAAPI host, and leaves the port unset so WAAPI can use its normal default.

Do not describe internal runtime defaults such as timeout constants, environment-variable wiring, coverage thresholds, default `WwiseConsole` paths, or scaffold directories as public config unless the user explicitly asks about implementation internals.

On first run, the skill also stores a project modification policy in `data/config.json`:

1. `never`: never execute project-changing operations.
2. `preview_then_confirm`: preview project changes first, then execute only after confirmation.
3. `allow_with_notice`: allow project changes for the configured project, but report each change.

The default policy is `preview_then_confirm`, and it persists with the rest of the user config.

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
6. `allow_destructive`: per-call opt-in for project-changing or destructive operations.
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

For complex WAAPI work, prefer the semantic planner before hand-writing dispatcher payloads. The planner maps structured semantic families to source-grounded builders, previews, readback plans, and dispatcher requests; it does not open Wwise, subscribe to topics, or dispatch live calls by default.

Use semantic families for these task types:

1. `intent_navigation`: read-only navigation and WAQL-shaped object discovery.
2. `crud_authoring`: create, set, delete, copy, move, property, reference, and undo-style authoring previews.
3. `system_design_preview`: candidate design plans that may combine safe reads with project-changing preview steps.
4. `asset_import_workflow`: audio import, tab-delimited import, and import evidence previews.
5. `soundbank_workflow`: soundbank inclusion, generation, external source, process definition, and evidence previews.
6. `switch_assignment_workflow`: guarded switch assignment add/remove previews and readback expectations.
7. `bounded_profiler_guidance`: bounded profiler parameter guidance and read summaries only.
8. `unsupported_runtime_boundary`: unsupported runtime, scheduler, Game Object View, RTPC ramp, narrative sequencing, or cross-app MCP requests.

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

If a requested mutation target path is not a valid direct writable parent for the requested object type, do not silently retarget the mutation. Explain the invalid target, identify likely writable child containers such as a `Default Work Unit` when supported by live state or grounded local evidence, and ask the user to confirm the intended writable child container before mutating.

## Safety guardrails

Project-changing and destructive operations are blocked by default. Only pass `allow_destructive=True` for a clearly requested change, after previewing when possible, and only against a project the user intentionally chose for that operation. Do not casually target a user's active production project.

Treat operations such as object deletion, object creation, property mutation, imports, soundbank changes, switch container assignment changes, and undo-group mutations as potentially destructive. Prefer read-only queries and dry runs until the requested edit is clear.

Keep runtime data, logs, auth state, and evidence artifacts out of git unless the user or plan explicitly asks for committed evidence. Do not claim Windows validation has passed unless the task provides real Windows-host evidence.

## Resources and documentation

The prompt should not load every reference file up front. Python code reads versioned manifests, semantic source notes, WAQL resources, and deferred registries for the selected version and task. The structured `resources/semantic/<version>/source_notes.json` files are the runtime semantic source-note resource.

Their `protocol` and `source_urls` fields point back to repository source-evidence history, which lives in root `references/` as development material outside the packaged runtime path. Runtime dispatcher and builder flows should rely on local packaged resources, not large prompt-loaded 2025 reference files.

## Skill layout

Key paths:

1. `scripts/run.py`: skill-local script runner.
2. `wwise_waapi/dispatcher.py`: generic WAAPI function and topic dispatcher.
3. `wwise_waapi/subscriptions.py`: bounded topic waits and cancellable listeners.
4. `wwise_waapi/manifest.py`: versioned manifest loading and reflection helpers.
5. `wwise_waapi/builders/`: semantic builders and preview objects.
6. `resources/manifest/<version>/`: generated API manifests.
7. `resources/semantic/<version>/`, `resources/waql/<version>/`, and `resources/deferred/<version>.json`: versioned runtime supporting resources loaded only when needed. Root `references/` and `references/semantic/<version>/` keep historical source-evidence markdown for development review outside the packaged runtime path.
