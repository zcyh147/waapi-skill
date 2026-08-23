---
name: waapi-skill
description: Test-only deep audio import interface for the sealed #52 MVP campaign.
---

# Deep audio import MVP

This is a test-only fake Gateway. It cannot connect to or change Wwise.

Read this file exactly once with `cat` as the sole first shell command. Do not
use Python, `rg`, `find`, `ls`, or `--help` to read or inspect the Skill.

Then use only the adjacent `scripts/run.py gateway.py` Gateway entrypoint. The
first Gateway subcommand is exactly `mvp-context --family <family>`. Use one of
the four family values below and do not omit the `--family` flag. Use only the
returned opaque handles and high-level command schemas.

Start `mvp-context` with the business family named by the request: `weather`,
`rifle`, `footsteps`, or `weapons`. Follow only that result's disclosed
high-level commands.

1. Declare a requested business container with `mvp-structure` when needed.
2. Declare each complete new Sound with `mvp-asset`, or one existing-target
   re-import with `mvp-existing-asset`.
3. Run `mvp-preview` once after every requested business fact is present.
4. Stop after the Preview and summarize it. Nothing is executed in this MVP.

Never supply or discuss a complete Wwise mutation path, native `objectType`,
metadata scope or token, native import row, action order, batch boundary,
revision, JSON request, or shell quoting. Those are fake-Gateway compiler
responsibilities.
