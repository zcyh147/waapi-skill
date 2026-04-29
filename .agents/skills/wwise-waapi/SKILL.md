---
name: wwise-waapi
description: Use this skill when working on the Wwise WAAPI skill scaffold, bootstrap scripts, pytest coverage stack, or any later Wwise WAAPI automation work in this repo. It should be consulted whenever the task touches the `.agents/skills/wwise-waapi/` package, its CLI runner, its tests, or its generated runtime data.
---

# Wwise WAAPI Skill Scaffold

This skill is the foundation for the Wwise WAAPI automation package. It provides the local Python package layout, venv bootstrap path, pytest markers, and a bounded headless WwiseConsole lifecycle gate for later WAAPI reflection work.

## Use this scaffold for

- package and CLI bootstrapping
- config/path resolution
- test scaffolding and coverage gates
- headless lifecycle launch/probe/cleanup for WwiseConsole WAAPI
- later implementation of manifests, dispatcher, subscriptions, and deferred registry

## Current contract

- Use `python .agents/skills/wwise-waapi/scripts/run.py --help` for wrapper help.
- Keep runtime data out of git.
- Default pytest runs must skip `live` and `destructive` tests unless the matching env vars are present.
- Headless Wwise tests must use dynamic ports, bounded timeouts, stdout/stderr capture, and reliable cleanup.
- Track overall coverage at 85%+; core modules should be treated as 95%+ targets as the implementation grows.

## Layout

- `scripts/run.py` - thin command wrapper
- `scripts/setup_environment.py` - venv bootstrapper
- `scripts/config.py` - script constants and coverage targets
- `wwise_waapi/` - importable package skeleton
- `tests/unit/` - fast tests
- `tests/live/` - Wwise-gated tests
- `tests/destructive/` - explicit opt-in tests

## Notes

Live Wwise tests remain opt-in with `WWISE_LIVE=1`; do not point tests at user projects or mutate project data.
