[English](./README.md) · [简体中文](./README.zh-CN.md)

<div align="center">

# WAAPI Skill

**Control Wwise Authoring with natural language.**

Without asking an AI agent to write WAAPI payloads by hand.

[![Platforms](https://img.shields.io/badge/Platforms-macOS%20%7C%20Windows-0078D4?style=flat-square)](#requirements)
[![Wwise](https://img.shields.io/badge/Wwise-2021.1–2025.1-5965E0?style=flat-square)](#supported-versions)
[![Python](https://img.shields.io/badge/Python-3.11–3.13-00897B?style=flat-square)](#requirements)
[![MIT](https://img.shields.io/badge/License-MIT-64748B?style=flat-square)](./LICENSE)

### [Download Latest](https://github.com/zcyh147/waapi-skill/releases/latest)

[Install](#install) · [Quick start](#quick-start) · [Coverage](./skills/waapi-skill/references/waapi-coverage.md) · [Report an issue](https://github.com/zcyh147/waapi-skill/issues)

</div>

---

WAAPI Skill is a local Agent Skill with a packaged, version-aware
Gateway. You describe the result you want; the Agent selects the right
operation and supplies a small set of business values, while the Gateway builds
the exact WAAPI request, previews changes, and verifies the result.

It runs locally, does not require an always-on MCP server, and works with any
agent that can load a Skill directory and run local scripts.

## Highlights

- **Natural-language Wwise workflows** — ask for outcomes instead of API
  names, object types, GUIDs, paths, or JSON payloads.
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

Connect to either **Wwise Authoring** or **WwiseConsole**; the Gateway detects
the host automatically. Reading the current selection, controlling the UI,
and monitoring UI events require Authoring. Available operations depend on
the connected host and Wwise version.

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
npx skills add zcyh147/waapi-skill --skill waapi-skill
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

<details>
<summary>Development and diagnostics: direct Gateway access</summary>

The Agent normally operates the Gateway on your behalf. For development,
diagnostics, or external automation, it can also be invoked directly from a
source checkout:

```bash
python skills/waapi-skill/scripts/run.py gateway.py config-set --wwise-version 2025.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy ask_before_changes
python skills/waapi-skill/scripts/run.py gateway.py status
```

The first invocation automatically prepares the Skill-local Python environment.
If Windows exposes Python as `py`, use that command instead of `python`.

</details>

## Scope and validation

The project covers the complete reviewed public surface of its packaged
WwiseConsole and Authoring profiles. Coverage is version-aware and does not
turn unsafe native fields or unsupported hosts into fake support.

The repository includes program tests, live read-only tests, destructive
sandbox tests, and fresh-agent semantic tests on macOS and Windows. Exact route
counts, version boundaries, and evidence are kept outside this user overview:

The October integration expansion has completed its macOS program and non-live
gates, copied-project preparation, and scoped music/RTPC Gateway checks. Its
new-model Fresh Agent pilot and final integration acceptance remain pending.

- [Detailed coverage](./skills/waapi-skill/references/waapi-coverage.md)
- [Test inventory and evidence](./tests/TEST_INVENTORY.md)
- [Skill contract](./skills/waapi-skill/SKILL.md)

## Skill or MCP?

Use this project when you want a local, version-aware Agent Skill with no
always-on server and tightly packaged behavior. Choose a Wwise MCP server when
your client specifically requires MCP-native interoperability or a persistent
service boundary.

## Feedback

Found a problem? [Open an issue](https://github.com/zcyh147/waapi-skill/issues)
with your Wwise version, operating system, Agent client, reproduction steps,
and error message. Remove sensitive project information before sharing logs
or conversation excerpts.

## License

[MIT](./LICENSE)


## Developer notice regressions

For quick notice, fake task-runner and fake archive feedback during development:

```bash
ci/test.sh --mode notice-fast -- -q -ra
```

This Poetry-backed command uses the explicit selection in
[`ci/notice-fast-test-nodes.txt`](./ci/notice-fast-test-nodes.txt), forces non-live
flags, and starts no model, Wwise or network client. Use `--collect-only` to
inspect selected tests; approved adjudication regressions can be added to the
same manifest. Extra test paths and collection overrides are rejected, and an
empty selection or failing test returns a failure status. `--mode focused`
remains the real Wwise matrix alias.

A quick result is development feedback only. Run complete Non-live and the
required final acceptance on the reviewed, frozen combined candidate; results
from an earlier candidate do not replace those gates.

Developer and Fresh campaign launchers emit a compact `test-readiness` JSON
record with status, reason, and phase duration before expensive test dispatch.
Selected real lanes check versioned paths, project version, sealed fixture/media
payloads when a fixture manifest exists, and conflicts scoped to the selected
source/sandbox. On macOS, real lanes also exclude other active real lanes
across roots because Audiokinetic wrappers share the Wwise2019x64 bottle.
Custom installed SampleProjects do not need a repository manifest. Complete
Non-live checks the five static fixture payloads and scoped gate conflicts;
focused fake selections remain independent of unrelated fixtures. Program,
Non-live, and notice-fast do not require live configuration;
archive verify-only retains its existing evidence checks without current live
readiness. A blocked result requires an explicit prerequisite repair and retry:
readiness never installs, hydrates, edits configuration, or terminates Wwise.
