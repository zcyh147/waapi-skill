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
- gateway-issued confirmation tokens bound to immutable transaction previews
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

Coverage is counted by **Wwise version/API row** because the same URI can have a different schema, route, or safety decision in each Wwise release. A row counts as covered only when the packaged gateway has a public execution contract for it; a hard boundary or documentation-only description does not count. Live host, version, and safety preconditions remain separate and must still pass before dispatch.

The default `wwise-console` profile is the canonical WwiseConsole-reflected
surface:

| Wwise version | Reflected rows | Packaged route rows | Routed functions | Routed topics | Registry exclusions |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2021.1` | 126 | 124 | 97 | 27 | 2 |
| `2022.1` | 144 | 142 | 110 | 32 | 2 |
| `2023.1` | 181 | 179 | 147 | 32 | 2 |
| `2024.1` | 178 | 178 | 148 | 30 | 0 |
| `2025.1` | 185 | 185 | 154 | 31 | 0 |
| **Total** | **814** | **808** | **656** | **152** | **6** |

Those 808 rows represent **198 unique routed WAAPI URIs**. This is packaged
interface coverage, not a claim that all 808 rows dispatch on WwiseConsole:
the three UI-command routes retained in each 2021.1–2023.1 Console-reflected
manifest still require a live Authoring host and fail before business dispatch
on WwiseConsole. The separate
`wwise-authoring-ui` profile adds only the five fixed
`ak.wwise.ui.commands.*` URIs reflected from real Wwise Authoring:

| Wwise version | Packaged overlay rows | Packaged route rows | Routed functions | Routed topics | Registry exclusions |
| --- | ---: | ---: | ---: | ---: | ---: |
| `2021.1` | 126 | 126 | 99 | 27 | 0 |
| `2022.1` | 144 | 144 | 112 | 32 | 0 |
| `2023.1` | 181 | 181 | 149 | 32 | 0 |
| `2024.1` | 183 | 183 | 152 | 31 | 0 |
| `2025.1` | 190 | 190 | 158 | 32 | 0 |
| **Total** | **824** | **824** | **670** | **154** | **0** |

The Authoring profile represents **200 unique routed WAAPI URIs**. On a matching
Authoring host, all 824 rows have a public route. It is
the Console manifest plus a narrowly reflected UI-command supplement, not a
claim that the complete Authoring API inventory was reflected. The gateway
selects the live host profile from `getInfo.isCommandLine`; UI-command calls
are rejected before business dispatch on WwiseConsole. The recorded command-ID
counts—317, 451, 475, 594, and 623 for Wwise 2021.1 through 2025.1—are observed
project/plugin/add-on snapshots, not runtime allowlists. Execution always
checks the current live `getCommands` result.

The five Authoring resources were collected with 35 read-only WAAPI calls in
total: per version, one `getInfo`, five fixed-URI `getSchema` calls, and one
`getCommands`. No live UI command was executed, registered, or unregistered.
Those transaction paths and the strengthened `object.createPlugin` readback
verifier are program/fake-client evidence in this candidate, not new live
business-mutation evidence.

Inspect either packaged profile offline with
`gateway.py capabilities --profile wwise-console` or
`gateway.py capabilities --profile wwise-authoring-ui`; this catalog option
cannot override the profile detected from a live host.

Both profiles route APIs through fixed commands, bounded direct calls, bounded
topic waits, confirmed transactions, isolated I/O transactions, or the
same-connection Undo Group composite. Lua file routes accept only an existing
`.lua` file whose path, size, and hash are rebound, while Wwise 2025.1 also has
an exact inline-source route; `source_authority` is a caller assertion, not
runtime proof of conversational provenance. The Skill never generates,
repairs, or wraps Lua. Private debug APIs use bounded reads/topics or explicit
non-retry transactions, with restart/assert/crash terminating in an
indeterminate lifecycle result.

The named operation layer also provides closed, version-aware business contracts for object creation and mutation, plug-in creation, RTPC/platform-link editing, audio import, SoundBank workflows, Lua/debug operations, screenshots, and Authoring UI command execution/registration/unregistration. `object.createPlugin` accepts only an exact class ID and a closed Source/Effect descriptor, uses fixed Effect references in `2022.1` or an appended EffectSlot in later versions, and verifies the created plug-in through live readback. UI command execution verifies only the reflected empty result—not the arbitrary GUI or project effect—while registration and unregistration additionally verify live command-ID membership. For `soundbank.generate`, Wwise `2021.1` derives its project and output context from the live Project object's `filePath` and `workunitIsDirty` accessors plus a contained, hashed, strictly parsed `.wproj`; no caller-authored project layout is accepted. Later versions bind the reflected `core.getProjectInfo` result. These routes bind an immutable preview to the later confirmation and use the strongest available operation-specific readback instead of trusting only a successful WAAPI response. Once a URI has an implemented dedicated operation, the generic `waapi.call` fallback is rejected with `DEDICATED_OPERATION_REQUIRED` so raw payloads cannot bypass that contract.

The focused code-only gate currently runs **1918 program tests**, including one packaged-route-contract case for every covered default-profile version/API row, the separate Authoring overlay/UI-command contracts, the configurable and explicitly unbounded topic-wait lifecycle, the gateway-owned conversation-context contract, and the named-operation contract/verifier matrices above. This proves packaged routing, schema handling, safety boundaries, I/O confinement, transaction behavior, fake-dispatch execution, and deterministic onboarding facts; it is not a claim that all 808 rows have been exercised against a real Wwise process. The completed memory-off `h80-release-c38` campaign separately passed all 80 approved real-Wwise heavy-API scenarios (70 on 2022.1, five on 2024.1, and five on 2025.1); that evidence applies to those scenarios and their sealed candidate, not the whole interface. See [the detailed five-version coverage contract](./skills/waapi-skill/references/waapi-coverage.md).

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

The gateway default for every Topic wait is 10 seconds, and any user-supplied positive finite duration is accepted through gateway-global `--timeout`. When the user omits a duration for `ak.wwise.core.soundbank.generated`, the Skill explicitly invokes the same gateway with `--timeout 120` and tells the user that actual choice before starting; 120 seconds is a Skill policy, not a second gateway default. An explicit `wait-topic --no-timeout` request waits until the requested events arrive or the user cancels it. No-timeout mode is not an unlimited output stream: `wait-topic` still collects a fixed `--event-count` from 1 through 64, returns one terminal JSON document, and keeps the aggregate result under the topic contract's 256 KiB ceiling. Its recursive JSON match is applied to each candidate event, and cleanup unsubscribes after success, timeout, or cancellation. Single-event success exposes the validated publish payload under `event`; multi-event success exposes ordered `events` plus requested/actual counts, and every payload is validated against the versioned publish schema. Collection stops at the requested count, so an independent publisher/oracle is still required to prove that no extra later event occurred. Do not match `object.created` by the requested final name: the notification is emitted before naming completes. For the packaged ActorMixer probe, Wwise 2021.1-2024.1 reports `ActorMixer` at notification time and Wwise 2025.1 reports its underlying `PropertyContainer`; correlate the returned object GUID with a trusted publisher when exact event ownership matters.

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

Inspect the packaged request contract first. `preview` returns an immutable
transaction id and full artifact hash for review. After the user confirms that
preview in a later message, `transaction-show --summary-only` reopens the stored
transaction and returns its short, state-bound `confirmation.token` plus the
exact next command. Use that token for the normal confirmation flow:

```bash
python scripts/run.py gateway.py operation-schema object.setNotes
python scripts/run.py gateway.py preview \
  --request-json '{"contract":"waapi-skill.operation-request/v1","operation":"object.setNotes","arguments":{"object":{"kind":"path","value":"\\Events\\Default Work Unit\\Target"},"value":"Reviewed"}}'
python scripts/run.py gateway.py transaction-show <transaction-id> --summary-only
python scripts/run.py gateway.py confirm <transaction-id> --confirmation-token <confirmation-token>
python scripts/run.py gateway.py execute <transaction-id>
python scripts/run.py gateway.py verify <transaction-id>
```

Run each phase separately and use the complete returned
`next_command.shell_command` rather than rebuilding it. The alternative
`confirm <transaction-id> --artifact-hash <full-artifact-hash>` spelling remains
available only for legacy transactions and programmatic compatibility; new
agent workflows should use the token returned by `transaction-show`.

The gateway is the public interface. Do not import internal runtime modules, construct a `WaapiClient`, create a one-off helper script, or use inline Python to complete a Wwise task. If the gateway reports no packaged route, return that unsupported boundary instead of synthesizing code.

Manifest reflection is discovery, not permission. The generic `call` route exposes only an immutable reviewed set of recursively validated, result-bounded reads; the two zero-input reflection inventories are merely fast paths within that set. Wwise 2025.1 Media Pool queries first discover exact field names through `mediaPool.getFields`, then call `mediaPool.get` with enforced limits of 200 results, 16 filters, 8 databases, and 32 unique return fields. Broader reads require a confirmed transaction, while fixed commands and topic waits remain exact allowlists. New or unreviewed functions and topics fail closed regardless of names such as `get`, `verify`, or `dump`; `--dry-run` cannot bypass a fixed, transaction, topic, or unsupported route boundary.

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
