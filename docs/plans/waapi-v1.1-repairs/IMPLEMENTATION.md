# Implementation checkpoint

Started 2026-10-17 by explicit user request to implement-spec.
Integration branch: `codex/waapi-v11-repairs`; review base: `f633403a`.
Draft PR: https://github.com/zcyh147/waapi-skill/pull/173

## Scope and budget

All supported 2021.1–2025.1 implementation/program lanes are required. Native-unavailable branches require explicit tested boundaries. Tickets are in English. First Fresh batch is four Mac workflows only; no additional Fresh or reruns without user approval. Do not operate on the Lyra user project.

## Current state

- #164: five-version route/schema ledger and source-backed policy/contract mapping merged (`a79659d0`). The ledger explicitly assigns unknown equivalence/evidence to residual review groups; it does not claim complete functional coverage. Final source-seal reconciliation is pending.
- #165: configuration-only runtime and existing fixture/Broker migration merged. Current Draft/transaction bindings reject a changed configuration before connection. Final combined gates pending.
- #166: metadata list/detail/page/selection implementation merged; 381 focused tests passed. Compact multi-field discovery response regression is being repaired. Fresh F1 preparation pending.
- #167: conditional dependency implementation merged; real-Wwise validation found exact UI-only Show and self-override metadata that focused fixtures missed. Narrow fixes and compact Preview derived-change disclosure are in the dependencies worktree. All five real lanes are in progress sequentially.
- #168: same-call GameParameter creation merged (`684fbcdc`), with 442 focused tests passed. Public Gateway native tests passed all five versions on candidate `90018ae0`; each independently verified Min=-12, Max=36, InitialValue=7 and the created identity. Earlier native feasibility evidence remains separate.
- #169: standalone Effect ShareSet implementation merged. Public Gateway native tests passed 2022.1–2025.1 on candidate `df8e0610`; 2021.1 has an explicit tested native object.set boundary. These fixtures do not prove every plugin/property combination.
- #170: receipt-driven recovery under the existing three policies merged (`57e3085a`); 184 focused tests passed. Unknown original writes are never replayed.
- #171: persistent project/output retention merged, with follow-up fixes preserving terminal cleanup flags and paired UI registration cleanup (`7ad519ea`). Latest focused validation: 362 plus 53 tests passed.
- #172: new opt-in four-workflow Mac Fresh profile is being connected to the existing campaign, Broker, task runner and archive verifier. No Fresh Agent run has started. Native F1 plugin metadata attestation is still required.

## Integration verification

The fixed Program gate has not yet passed. Its second diagnostic run on `e90c9c7c` stopped at 30 failures with 6100 passed / 3 skipped; it is not acceptance evidence. Follow-up fixes include stale live CLI flags, cleanup semantics, schema expectations and documentation read budgets. On `7ff67f1e`, the affected documentation/UI/plugin/composer tests passed 163 / 1 deselected (the pending reviewed schema digest). The registry follow-up passed 363 / 1 deselected. Source-derived seal updates and a fresh complete Program and Non-live run remain required.

Native lifecycle receipts are held in ignored `.waapi-skill-state` roots in main and the gameparameter/dependencies worktrees. Preserve them before archiving worktrees. Each completed PASS checked unchanged source project hashes/mtime, owned sandbox cleanup and no residual scoped Wwise processes. Failed development probe roots remain sealed and quarantined. No Windows real-host or Fresh validation is claimed.

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

## Current real-host authorization

The user confirmed the other Wwise work had finished and authorized continuing normal readiness checks. The earlier user-process blocker is resolved; never bypass the normal gate or terminate a user process. The metadata implementer currently owns the single real-Wwise slot for sequential attenuation tests, then yields it to the Fresh-profile implementer for a deterministic F1 metadata preflight. No Fresh launch is authorized until the final candidate and four-workflow schedule are frozen.
