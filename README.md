[English](./README.md) · [简体中文](./README.zh-CN.md)

# Wwise WAAPI Skill

Control Wwise Authoring with natural language—without asking an AI agent to
write WAAPI payloads by hand.

Wwise WAAPI Skill is a local Agent Skill with a packaged, version-aware
Gateway. You describe the result you want; the Agent selects the right
operation and supplies a small set of business values, while the Gateway builds
the exact WAAPI request, previews changes, and verifies the result.

It runs locally, does not require an always-on MCP server, and works with any
agent that can load a Skill directory and run local scripts.

## Highlights

- **Natural-language Wwise workflows** — ask for outcomes instead of API
  names, object types, GUIDs, paths, or JSON payloads.
- **Broad Authoring coverage** — query and edit objects, import or reimport
  audio, manage Events and Switch assignments, generate SoundBanks, use
  Profiler/runtime operations, subscribe to events, and more.
- **Five Wwise release lines** — version-specific contracts for `2021.1`,
  `2022.1`, `2023.1`, `2024.1`, and `2025.1`.
- **Safe project changes** — every mutation goes through an immutable Preview,
  explicit policy, one execution, and result verification.
- **Local and bounded** — credentials, project data, runtime state, and evidence
  stay local; unsupported or unsafe requests fail with a clear boundary.
- **Cross-platform tested** — developed and validated on macOS and native
  Windows, including real Wwise and fresh-agent workflows.

## What can it do?

Typical tasks include:

- inspect selected objects, hierarchy, properties, references, buses, and
  project state
- create, copy, move, rename, update, or delete Wwise objects
- import audio and build object/Event structures from media files
- edit volume, looping, notes, Output Bus, RTPC, platform links, and metadata
- maintain Switch Container and State/Switch assignments
- generate and inspect SoundBanks and related artifacts
- run supported Authoring UI, SoundEngine, Profiler, transport, CLI, Lua, and
  Topic subscription workflows

The packaged profiles expose every reviewed and permitted route in their
supported Wwise versions. Host-only, version-only, dangerous, or unverifiable
capabilities return an explicit boundary instead of guessing.

## Supported versions

| Wwise | Packaged support |
| --- | --- |
| `2021.1` | Yes |
| `2022.1` | Yes |
| `2023.1` | Yes |
| `2024.1` | Yes |
| `2025.1` | Yes |

Two host profiles are available:

- **WwiseConsole** for the reflected command-line surface
- **Wwise Authoring UI** for the same core surface plus supported UI commands

The Gateway detects the connected host automatically. Authoring-only commands
do not pretend to work through WwiseConsole.

## Requirements

- Python `3.11`–`3.13`
- a supported Wwise installation
- a local Wwise project with WAAPI available
- an agent or tool runner that supports local Skills

The Skill creates and prepares its own Python environment automatically on
first use. Node.js and npm are required only for the Skills CLI installation
method below.

## Install

### Agent-assisted installation

Provide [this repository](https://github.com/zcyh147/waapi-skill) to an Agent
that supports local Skills and request installation of the `waapi-skill` Skill.

### Skills CLI

Install the Skill directly with the Skills CLI:

```bash
npx skills@latest add zcyh147/waapi-skill --skill waapi-skill
```

## Quick start

Open the target project in Wwise. Under `Project > User Preferences`, enable
`Wwise Authoring API (WAAPI)` and confirm the WAMP port. The default local port
is `8080`; if your project uses another port, provide the same value to the
Skill.

Once the Skill is installed, use normal language in your Agent conversation:

> Configure this Skill for Wwise 2025.1 using the local WAAPI endpoint on port
> 8080, keep the `ask_before_changes` policy, and verify the connection.

> List the Events under the Default Work Unit.

> Under Weather, import Rain and Wind, loop both indefinitely, set them to
> -4 dB and -6 dB, and route them to the Weather Bus. Show me the Preview first.

> Reimport the rifle tail audio without changing the Sound's other settings.

The Agent follows the Skill's Gateway-generated continuation. You do not need
to translate these requests into WAAPI schemas, Python commands, or command-line
arguments.

## Change policies

- `read_only` — allow inspection and block project changes
- `ask_before_changes` — show the Preview and wait for confirmation; this is
  the default
- `allow_changes` — show notice, then execute and verify the Preview without a
  second confirmation message

All three modes preserve the same closed Gateway boundary. A successful WAAPI
response alone is not treated as proof that the requested business result was
achieved.

## How it works

```text
Natural-language request
        ↓
Agent selects an operation and supplies closed business values
        ↓
Gateway builds the version-correct WAAPI request and execution plan
        ↓
Read directly, or Preview → authorize → execute once → verify
        ↓
Wwise
```

The key design boundary is simple:

- The **Agent** handles natural language and chooses user-facing values such as
  object names, media files, `volume_db=-4`, or `loop=Infinite`.
- The **Gateway** owns Wwise types, full paths, metadata lookup, native enums,
  GUIDs, dependency order, batching, serialization, Preview state, and
  verification.

There is no LLM inside the Gateway. It is deterministic, uses versioned
reflected resources, and loads detailed guidance only when the current task
needs it. This keeps the experience Skill-like while giving it the stable tool
boundary normally expected from a well-designed MCP integration.

## Direct Gateway access (optional)

The Agent normally operates the Gateway on your behalf. For development,
diagnostics, or external automation, it can also be invoked directly from a
source checkout:

```bash
python skills/waapi-skill/scripts/run.py gateway.py config-set --wwise-version 2025.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy ask_before_changes
python skills/waapi-skill/scripts/run.py gateway.py status
```

The first invocation automatically prepares the Skill-local Python environment.
If Windows exposes Python as `py`, use that command instead of `python`.

## Scope and validation

The project covers the complete reviewed public surface of its packaged
WwiseConsole and Authoring profiles. Coverage is version-aware and does not
turn unsafe native fields or unsupported hosts into fake support.

The repository includes program tests, live read-only tests, destructive
sandbox tests, and fresh-agent semantic tests on macOS and Windows. Exact route
counts, version boundaries, and evidence are kept outside this user overview:

- [Detailed coverage](./skills/waapi-skill/references/waapi-coverage.md)
- [Test inventory and evidence](./tests/TEST_INVENTORY.md)
- [Skill contract](./skills/waapi-skill/SKILL.md)

## Skill or MCP?

Use this project when you want a local, version-aware Agent Skill with no
always-on server and tightly packaged behavior. Choose a Wwise MCP server when
your client specifically requires MCP-native interoperability or a persistent
service boundary.
