# Implementation checkpoint

Started 2026-10-17 by explicit user request to implement-spec.
Integration branch: `codex/waapi-v11-repairs`; review base: `f633403a`.
Draft PR: https://github.com/zcyh147/waapi-skill/pull/173

## Scope and budget

All supported 2021.1–2025.1 implementation/program lanes are required. Native-unavailable branches require explicit tested boundaries. Tickets are in English. First Fresh batch is four Mac workflows only; no additional Fresh or reruns without user approval. Do not operate on the Lyra user project.

## Current state

- #164: reproducible enumeration/checker merged (`badc3fde`), focused tests 5 passed. Native-to-business branch mapping audit is still incomplete; keep the issue open. See `docs/branch-coverage-audit.md` for evidence and next mapping pass.
- #165: runtime merged at `9edb285c`; focused tests 111 passed. Existing test/harness migration remains in progress; combined gate pending.
- #166: merged at `3213643a`; six-file focused suite 381 passed, including five-version fake Preview/execute/verify. Real evidence pending.
- #167: merged at `29e6b553`; focused suite 113 passed. 2021 setReference uses explicit prerequisite workflow; 2022+ object.set supports combined changes. Real evidence pending.
- #168: frozen deterministic feasibility probe at `19dfdd24` in gameparameter worktree. ci readiness blocked before launch because user Lyra WwiseConsole is running; no test Wwise or sandbox started. Awaiting user closure; independent code work continues.
- #169: implementation and focused program tests in progress; real validation also awaits readiness.
- #170: pending.
- #171: merged at `54c613ec`; focused cleanup/lifecycle suite 218 passed, post-merge 11 passed. Final gate pending.
- #172: pending; no Wwise or Fresh acceptance run started.

## Working copies

- Config runtime: `/Users/xiye/.codex/worktrees/waapi-config/waapi-skills`, branch `codex/waapi-config-only`.
- Config fixture/harness migration: `/Users/xiye/.codex/worktrees/waapi-config-tests/waapi-skills`, branch `codex/waapi-config-test-migration`.
- Metadata: `/Users/xiye/.codex/worktrees/waapi-metadata/waapi-skills`, branch `codex/waapi-metadata-pages`.
- Audit: `/Users/xiye/.codex/worktrees/waapi-audit/waapi-skills`, branch `codex/waapi-branch-audit` (merged).
- Prepared, unused worktrees: waapi-cleanup, waapi-dependencies, waapi-sharesets under the same managed worktree root.

Developer interpreter: `/Users/xiye/Library/Caches/pypoetry/virtualenvs/non-package-mode-nsP1lGog-py3.11/bin/python`, invoked through `ci/test.sh` with `WAAPI_TEST_PYTHON` where necessary.

## Real-host coordination

All five configured local installations and SampleProjects exist. At initial process inventory, a user Authoring process and Lyra Console on port 8081 were active in the Mac Wine environment. Recheck isolation before starting any real test. Existing ScenarioLifecycle private-HOME pattern (used by expansion) can provide a distinct effective Wine bottle; WINEPREFIX alone is overwritten by official launchers. Attest effective isolation before use. Do not terminate user processes or use user projects as test fixtures.

Auxiliary handoffs: `/tmp/waapi-165-migration.md` and `/tmp/waapi-v11-validation-handoff.md`. These are coordination notes, not permanent evidence or a replacement for tracker/spec.

## Active blocker

The normal ci entrypoint rejects any real Mac lane while other Wwise processes are active. Root has asked the user asynchronously to save/close the existing Wwise/Console when convenient. No permission to stop user processes or bypass readiness has been given. Do not treat proposed private-HOME isolation as overriding that gate.
