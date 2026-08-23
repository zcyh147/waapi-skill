---
name: waapi-skill
description: Test-only deep audio import interface for the sealed #52 MVP campaign.
---

# Deep audio import MVP

This is a test-only fake Gateway backed by the real MVP declaration compiler,
canonical request parser, and immutable Preview builder. Its live reads are
fixed fakes; it cannot connect to or change Wwise.

Read this file exactly once with `cat` as the sole first shell command. Do not
use Python, `rg`, `find`, `ls`, or `--help` to read or inspect the Skill.

Then use only the adjacent `scripts/run.py gateway.py` Gateway entrypoint. The
first Gateway subcommand is exactly `mvp-context --family <family>`. Use one of
the four family values below and do not omit the `--family` flag. Use only the
returned opaque handles and high-level command schemas.

Start `mvp-context` with the destination-bound business family: `weather` for
a Weather destination, `rifle` only for the one existing Rifle target,
`footsteps` for a Footsteps destination, and `weapons` for a bound Weapons
parent. Child names such as `Rifle_Mechanical` below Weapons do not select the
existing-target `rifle` family. Follow only that result's disclosed high-level
commands.

1. Declare a requested business container with `mvp-structure` when needed.
   A disclosed `parent_handle` already identifies the requested bound parent;
   never add another container with the same name. Weather explicitly asks for
   a new container, so its bound parent is only the place to create Weather.
2. Declare each complete new Sound with `mvp-asset`, or one existing-target
   re-import with `mvp-existing-asset`. Append `--replace` only when the user
   explicitly requests replacement. For a disclosed long-tail field, pass its
   opaque `--field-handle` with the requested `--field-number`; never replace
   the handle with a Wwise token.
   Different import modes cannot share one Preview.
3. Never construct `mvp-preview` yourself. When a declaration result contains
   `next_command`, execute only the complete field named by
   `next_command.copy_instruction.source_field`, verbatim and immediately.
   After that Preview, start a new `mvp-context` before declaring another mode.
4. Stop after the Preview and summarize it. Nothing is executed in this MVP.

Never supply or discuss a complete Wwise mutation path, native `objectType`,
metadata scope or token, native import row, action order, batch boundary,
revision, JSON request, or shell quoting. Those are fake-Gateway compiler
responsibilities.
