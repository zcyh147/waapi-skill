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

WAAPI Skill lets an AI agent inspect and edit Wwise projects from natural-language
requests. Its local Gateway turns those requests into version-specific WAAPI
calls, previews changes, and checks the results.

It works with agents that can load a Skill directory and run local scripts.
No always-on MCP server is required.

## Highlights

- **Describe the task** — query objects, import audio, change settings, and
  generate SoundBanks without writing WAAPI requests.
- **Control project changes** — choose read-only access, confirmation before
  changes, or execution without a second confirmation.
- **Version-aware operations** — the Gateway uses the definitions for your
  configured Wwise version and reports unsupported requests clearly.
- **Local execution** — the Gateway runs on your machine, on macOS or Windows.

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

Some operations depend on the Wwise version or require Authoring rather than
WwiseConsole. Some object creation operations are not exposed by the Skill;
see the [known creation limits](docs/plans/full-waapi-coverage/SPEC.md#user-approved-remaining-creation-limits--2026-10-29).

## Supported versions

Supports Wwise **2021.1, 2022.1, 2023.1, 2024.1, and 2025.1**.

Connect to either **Wwise Authoring** or **WwiseConsole**; the Gateway detects
the host automatically. Reading the current selection, controlling the UI,
and monitoring UI events require Authoring.

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

The Agent handles the Gateway commands for you. You do not need to write Python
or WAAPI requests.

## Change policies

- `read_only` — allow inspection and block project changes
- `ask_before_changes` — show the Preview and wait for confirmation; this is
  the default
- `allow_changes` — show notice, then execute and verify the Preview without a
  second confirmation message

The Gateway checks results where the API allows it and states when an outcome
cannot be fully verified.

## How it works

```text
You describe a task
        ↓
The Agent selects a Skill operation
        ↓
The local Gateway prepares the request for your Wwise version
        ↓
Read directly, or preview → authorize → execute → check the result
```

The Agent interprets your request; the Gateway handles WAAPI parameters and
execution. The Gateway contains no language model. Your Agent client's model
and data-handling settings still apply to the conversation and tool results.

<details>
<summary>Development and diagnostics: direct Gateway access</summary>

The Agent normally operates the Gateway on your behalf. For development,
diagnostics, or external automation, it can also be invoked directly from a
source checkout:

```bash
python skills/waapi-skill/scripts/run.py gateway.py config-set --wwise-version 2025.1 --waapi-host 127.0.0.1 --waapi-port 8080 --project-modification-policy ask_before_changes
python skills/waapi-skill/scripts/run.py gateway.py status
```

Live commands and Drafts use the saved connection only. Temporary host/port
flags and connection environment variables cannot override it; `--version`
is reserved for offline catalog/schema browsing. To isolate a sandbox or a
second Skill copy, select a distinct `WAAPI_SKILL_CONFIG_PATH` and configure
it with `config-set`. Copying the Skill alone still shares the user config.

The first invocation automatically prepares the Skill-local Python environment.
If Windows exposes Python as `py`, use that command instead of `python`.

</details>

## Coverage and validation

The project has Python tests, real Wwise tests in isolated projects, and
fresh-agent workflow tests, with recorded runs on macOS and native Windows.
Results vary by version and workflow; these records do not mean every operation
has been tested on every supported platform and version.

- [Detailed coverage](./skills/waapi-skill/references/waapi-coverage.md)
- [Test results and known limitations](./tests/TEST_INVENTORY.md)
- [Agent instructions](./skills/waapi-skill/SKILL.md)

## Skill or MCP?

Use this Skill with an agent that can load local Skills and run scripts. If your
client requires an MCP connection, use a Wwise MCP server instead.

## Feedback

Found a problem? [Open an issue](https://github.com/zcyh147/waapi-skill/issues)
with your Wwise version, operating system, Agent client, reproduction steps,
and error message. Remove sensitive project information before sharing logs
or conversation excerpts.

## License

[MIT](./LICENSE)

AI training on this project is welcome under the MIT license.
