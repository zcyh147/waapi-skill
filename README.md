[English](./README.md) · [简体中文](./README.zh-CN.md)

# Wwise WAAPI Skill

Use this skill to automate **Wwise Authoring through WAAPI** with a version-aware, gateway-first workflow.

It is designed for **any local agent or tool runner** that can load a skill directory plus helper scripts. It is not tied to a specific coding assistant, and it does not depend on a separate MCP server.

---

## What this skill is for

This skill helps an agent work with Wwise safely and efficiently when the task involves:

- querying Wwise objects and project state
- routing structured intent through packaged gateway commands instead of ad hoc payload guessing
- handling multiple Wwise versions with version-scoped resources
- previewing project-changing operations before execution
- validating behavior with real tests instead of documentation-only claims

In practice, it gives an agent a **skill-local WAAPI interface**: a runner, one packaged gateway, versioned manifests, bounded topic waits, closed transaction operations, and safety rules.

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
- preview artifact hash confirmation for closed transactions
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

## Packaged API coverage

Coverage is counted by **Wwise version/API row** because the same URI can have a different schema, route, or safety decision in each Wwise release. A row counts as covered only when the packaged gateway can actually execute it; a hard boundary or documentation-only description does not count.

| Wwise version | Reflected rows | Executable rows | Executable functions | Executable topics | Excluded rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2021.1` | 126 | 119 | 93 | 26 | 7 |
| `2022.1` | 144 | 137 | 106 | 31 | 7 |
| `2023.1` | 181 | 170 | 139 | 31 | 11 |
| `2024.1` | 178 | 168 | 139 | 29 | 10 |
| `2025.1` | 185 | 175 | 145 | 30 | 10 |
| **Total** | **814** | **769** | **622** | **147** | **45** |

Those 769 rows represent **188 unique executable WAAPI URIs**. They are routed through fixed commands, bounded direct calls, bounded topic waits, confirmed transactions, isolated I/O transactions, or the same-connection Undo Group composite. The 45 excluded version rows represent 12 unique URIs limited to arbitrary Lua execution, unsafe/private debug surfaces, and unrestricted UI command registration/execution.

The focused code-only gate currently runs **957 program tests**, including one executable-route case for every covered version/API row plus the gateway-owned conversation-context contract. This proves packaged routing, schema handling, safety boundaries, I/O confinement, transaction behavior, fake-dispatch execution, and deterministic onboarding facts; it is not a claim that all 769 rows have been exercised against a real Wwise process. See [the detailed five-version coverage contract](./skills/waapi-skill/references/waapi-coverage.md).

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

### Packaged gateway execution model

The normal flow is:

1. detect or select the Wwise version
2. choose the fixed packaged gateway route for that intent
3. run a direct read-only command or create an immutable mutation preview
4. confirm and execute only through the closed transaction route
5. verify the result

### Read-first behavior for safe inspection

When config and connection details are already known, ordinary inspection requests should execute the direct read-only path first instead of drifting into documentation research.

### Bounded topic handling

Topic waits are supported with explicit bounded behavior instead of loose long-lived listener assumptions. The command timeout is an end-to-end budget, so the event wait reserves a small part of it for unsubscribe, evidence publication, and transport close. A successful `wait-topic` result exposes the validated WAAPI publish payload directly under `event`, while the dispatcher-only callback envelope remains private. Do not match `object.created` by the requested final name: the notification is emitted before naming completes. For the packaged ActorMixer probe, Wwise 2021.1-2024.1 reports `ActorMixer` at notification time and Wwise 2025.1 reports its underlying `PropertyContainer`; correlate the returned object GUID with a trusted publisher when exact event ownership matters.

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

The runner accepts only the packaged `gateway.py` and `setup_environment.py` entry points. Unknown, absolute, traversing, or symlinked script targets are rejected even if a helper file exists locally.

### 2. Configure version and WAAPI endpoint

Normal persisted config lives outside the installed Skill. The gateway resolves
the first applicable path in this order:

```text
$WAAPI_SKILL_CONFIG_PATH
$XDG_CONFIG_HOME/waapi-skill/config.json
$HOME/.config/waapi-skill/config.json
```

Inspect or change it through `gateway.py config-show` and `gateway.py
config-set`; do not hand-edit it. `skills/waapi-skill/data/config.json` is only
a read-only legacy fallback when no external config exists, and is never the
normal write target.

Public persisted fields are intentionally small:

- `wwise_version`
- `waapi_host`
- `waapi_port`
- `project_modification_policy`

### 3. Run read-only work through the gateway

Check the live version/project and query objects without composing WAAPI code:

```bash
python scripts/run.py gateway.py status
python scripts/run.py gateway.py query-object \
  --path '\Events\Default Work Unit' \
  --return-field id --return-field name --return-field type --return-field path
```

### 4. Use the closed transaction lane for project changes

Inspect the packaged request contract first. `preview` returns the transaction id and artifact hash that must be reused unchanged by the remaining commands:

```bash
python scripts/run.py gateway.py operation-schema object.setNotes
python scripts/run.py gateway.py preview \
  --request-json '{"contract":"waapi-skill.operation-request/v1","operation":"object.setNotes","arguments":{"object":{"kind":"path","value":"\\Events\\Default Work Unit\\Target"},"value":"Reviewed"}}'
python scripts/run.py gateway.py confirm <transaction-id> --artifact-hash <artifact-hash>
python scripts/run.py gateway.py execute <transaction-id>
python scripts/run.py gateway.py verify <transaction-id>
```

The gateway is the public interface. Do not import internal runtime modules, construct a `WaapiClient`, create a one-off helper script, or use inline Python to complete a Wwise task. If the gateway reports no packaged route, return that unsupported boundary instead of synthesizing code.

Manifest reflection is discovery, not permission. The generic `call` route exposes only the two zero-input, strictly validated reflection lists (`ak.wwise.waapi.getFunctions` and `ak.wwise.waapi.getTopics`). Other reads require a dedicated bounded command; fixed commands and topic waits are exposed only for exact URIs in immutable reviewed allowlists. New or unreviewed functions and topics fail closed regardless of names such as `get`, `verify`, or `dump`; `--dry-run` cannot bypass a fixed, transaction, topic, or unsupported route boundary.

---

## Safety model

- destructive operations are blocked by default
- project-changing steps should be previewed before execution
- confirmation must match the active immutable preview artifact
- unsupported runtime boundaries should fail clearly, not pretend to execute
- reflected functions and topics require an explicit reviewed public route
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
- `skills/waapi-skill/scripts/gateway.py` — the public packaged WAAPI interface
- `skills/waapi-skill/references/` — lane-specific gateway guidance loaded on demand
- `skills/waapi-skill/wwise_waapi/capabilities.py` — offline public-route catalog
- `skills/waapi-skill/wwise_waapi/operation_registry.py` — closed transaction operations and explicit boundaries
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

No. It is written as a local skill package with a packaged runner/gateway and markdown guidance. Any local agent workflow that can load and follow a skill directory can use it.

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
- **closed, agent-executable gateway routes**
- **safer mutation flow**
- **strong validation coverage**

If you want a local, version-aware, tested WAAPI skill rather than a broad always-on server abstraction, this is the right shape.
