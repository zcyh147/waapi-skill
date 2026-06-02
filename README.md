[English](./README.md) · [简体中文](./README.zh-CN.md)

# Wwise WAAPI Skill

Use this skill to automate **Wwise Authoring through WAAPI** with a version-aware, Python-first workflow.

It is designed for **any local agent or tool runner** that can load a skill directory plus helper scripts. It is not tied to a specific coding assistant, and it does not depend on a separate MCP server.

---

## What this skill is for

This skill helps an agent work with Wwise safely and efficiently when the task involves:

- querying Wwise objects and project state
- building WAAPI requests from structured intent instead of ad hoc payload guessing
- handling multiple Wwise versions with version-scoped resources
- previewing project-changing operations before execution
- validating behavior with real tests instead of documentation-only claims

In practice, it gives an agent a **skill-local WAAPI toolchain**: a runner, versioned manifests, semantic builders, dispatcher helpers, bounded subscriptions, and safety rules.

## Why this skill exists

Generic agents can talk about WAAPI, but that is not the same as operating Wwise reliably.

The hard parts are usually not the first API call. They are:

- choosing the correct Wwise version
- loading the right constraints for that version
- avoiding prompt bloat from giant schemas or docs
- handling mutation safety and confirmation correctly
- keeping live behavior grounded in real evidence

This skill solves those problems with a **version-aware local runtime** instead of relying on broad prompt context alone.

---

## Key advantages

### 1. On-demand loading instead of prompt stuffing

The skill does not front-load every reference file into context.

It loads only the resources needed for the current task and version, including:

- `resources/manifest/<version>/`
- `resources/semantic/<version>/`
- `resources/waql/<version>/`
- `resources/deferred/<version>.json`

That keeps the runtime focused, version-scoped, and easier to reason about.

### 2. Multi-version support is built in

Supported Wwise versions:

- `2021.1`
- `2022.1`
- `2023.1`
- `2024.1`
- `2025.1`

The skill is not pretending to be “one WAAPI prompt for every version.” It ships versioned manifests, semantic source notes, WAQL resources, and deferred registries so an agent can choose the right surface deliberately.

### 3. Safer mutation workflow

Project-changing operations are not treated as casual follow-ups.

The skill supports:

- read-only first paths for ordinary inspection
- preview-then-confirm mutation flow
- preview hash confirmation for semantic plans
- bounded destructive opt-in
- post-action verification and readback

### 4. Stronger test coverage than a docs-only integration

This repo includes more than static documentation. It includes:

- unit tests
- live read-only validation
- destructive sandbox validation
- semantic behavior validation
- version-scoped review packets and evidence models

The goal is not just to describe WAAPI correctly. The goal is to make the skill behave correctly under real use.

---

## Wwise MCP comparison

This skill and a Wwise MCP server solve overlapping problems, but they are not the same tool.

### Where this skill is stronger

- **On-demand resource loading** instead of broad always-on context
- **Version-scoped runtime assets** for `2021.1` through `2025.1`
- **Skill-local Python workflow** with no separate server process required
- **Preview-oriented authoring flow** with confirmation semantics
- **Extensive repo-native testing**, including sandbox and semantic validation

### Where a Wwise MCP server may be stronger

- persistent tool exposure through an MCP protocol
- easier reuse across clients that already standardize on MCP
- server-style integration when you want a long-lived process boundary

### Practical rule of thumb

Choose this skill when you want:

- a **local skill package**
- **version-aware WAAPI guidance and execution helpers**
- **tight safety rails** around mutation
- **tested, repo-local behavior** with on-demand loading

Choose a Wwise MCP server when you specifically need:

- **persistent server integration**
- **MCP-native client interoperability**
- a tool model centered on external server exposure rather than skill-local runtime assets

---

## Core features

### Version-aware manifests and semantic resources

The skill uses reflected manifests and versioned semantic notes so an agent can operate against the correct WAAPI surface without pretending all versions behave identically.

### Semantic planner + dispatcher model

The normal flow is:

1. detect or select the Wwise version
2. extract structured semantic intent
3. build a semantic preview or direct read-only plan
4. dispatch safely through the validated WAAPI layer
5. verify the result

### Read-first behavior for safe inspection

When config and connection details are already known, ordinary inspection requests should execute the direct read-only path first instead of drifting into documentation research.

### Bounded topic handling

Topic waits are supported with explicit bounded behavior instead of loose long-lived listener assumptions.

### Explicit unsupported boundaries

Some requests are intentionally out of scope, such as scheduler-like delayed runtime posting, Game Object View emitter control, timed runtime sequencing, or cross-app federation. Those boundaries are returned explicitly instead of being blurred into fake support.

---

## Quick start

### 1. Set up the local environment

From the repository root:

```bash
cd skills/waapi-skill
```

Then run:

```bash
python scripts/run.py --help
python scripts/run.py setup_environment.py
```

### 2. Configure version and WAAPI endpoint

The persisted config lives at:

```text
skills/waapi-skill/data/config.json
```

Public persisted fields are intentionally small:

- `wwise_version`
- `waapi_host`
- `waapi_port`
- `project_modification_policy`

### 3. Use the skill-local runner

Typical low-level example:

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
)
```

### 4. Prefer semantic planning for non-trivial work

For authoring, imports, soundbanks, switch assignments, or structured multi-step tasks, use the semantic planner path instead of hand-writing raw WAAPI payloads from scratch.

---

## Safety model

- destructive operations are blocked by default
- project-changing steps should be previewed before execution
- confirmation must match the active preview artifact for semantic plans
- unsupported runtime boundaries should fail clearly, not pretend to execute
- evidence, runtime data, and local auth state should stay local unless explicitly promoted

This skill is optimized for **honest boundaries and reproducible behavior**, not for “always say yes.”

---

## Testing philosophy

The validation story matters here.

This repo uses multiple layers:

- **unit tests** for builders, dispatcher behavior, resource layout, and contract rules
- **live read-only tests** for grounded WAAPI inspection behavior
- **destructive sandbox tests** for copied-project mutation safety
- **semantic validation** for real agent behavior in a local skill workspace

The point is simple: claims about support should come from executed validation, not just from copied docs or optimistic prompt wording.

---

## Skill layout

```text
.
├── README.md
├── README.zh-CN.md
└── skills/
    └── waapi-skill/
        ├── SKILL.md
        ├── data/
        ├── resources/
        ├── scripts/
        └── wwise_waapi/
```

Important paths:

- `skills/waapi-skill/SKILL.md` — the skill contract
- `skills/waapi-skill/scripts/run.py` — skill-local runner
- `skills/waapi-skill/wwise_waapi/dispatcher.py` — validated WAAPI dispatch
- `skills/waapi-skill/wwise_waapi/semantic_planner.py` — structured semantic planning
- `skills/waapi-skill/wwise_waapi/builders/` — preview-oriented builders
- `skills/waapi-skill/resources/manifest/<version>/` — reflected versioned manifests
- `skills/waapi-skill/resources/semantic/<version>/` — semantic source-note resources
- `skills/waapi-skill/resources/waql/<version>/` — WAQL guidance resources
- `skills/waapi-skill/resources/deferred/<version>.json` — explicit deferred/unsupported coverage boundaries

---

## When to use this skill

Use it when the task mentions:

- Wwise
- WAAPI
- Audiokinetic authoring APIs
- Wwise version selection
- object queries, creation, mutation, import, soundbanks, or switch assignments
- bounded topic subscriptions
- safe destructive previews or sandbox validation

---

## FAQ

### Is this tied to one coding agent?

No. It is written as a local skill package with Python helpers and markdown guidance. Any local agent workflow that can load and follow a skill directory can use it.

### Is this an MCP server?

No. This is a skill-local workflow, not a standalone MCP service.

### Does it support multiple Wwise versions?

Yes. That is one of the main design goals.

### Does it replace real testing?

No. It is designed to work together with real validation, including unit, live, destructive, and semantic test layers.

---

## Bottom line

This is a **Wwise WAAPI skill**, not a generic documentation wrapper.

Its strengths are:

- **on-demand loading**
- **multi-version support**
- **structured semantic planning**
- **safer mutation flow**
- **strong validation coverage**

If you want a local, version-aware, tested WAAPI skill rather than a broad always-on server abstraction, this is the right shape.
