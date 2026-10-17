# Full WAAPI coverage implementation checkpoint

Parent: [Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).
User approved publication and implement-spec on 2026-10-17. The persistent Goal
is active. Integration branch: `codex/full-waapi-coverage`; base: merged PR #173
at `07c20232`. Do not merge main without a later explicit user request.

## Task graph

All 21 English tickets (#175–#195) are published as native sub-issues; all
36 blocking edges were verified. The proposal JSON preserves exact mappings.
The implementation frontier starts with #175 (native catalogs), then #176
(completion and ownership), then the unblocked functional slices. Track verified
integration commits separately from issue closure; final main merge closes
completed tickets through normal PR references.

## Active work

- Draft integration PR: [#196](https://github.com/zcyh147/waapi-skill/pull/196).
- #175 is assigned and in progress on isolated branch `codex/full-native-catalog`.
  The first collector/discovery slice was integrated at `3c8406f3`; this exact
  candidate was held unchanged for all native collection.
- All five Console captures completed with source full hashes/mtimes unchanged,
  archived receipts, clean shutdown and disposable sandbox removal. These are
  native reflection results, not business execution or Fresh acceptance.
- All five Authoring function/Topic lists and schemas were captured. 2021/2022
  completed cleanly. 2023 completed its catalog, but the one-off owner's immediate
  port check failed; a separate bounded follow-up proved port release and no
  residual process. Its original verdict is retained. 2024/2025 raw captures
  correctly stopped catalog publication for missing UI definition documents;
  separately attested same-build UI/WAFM definitions complete offline derivation
  into new roots, without changing the original failed receipts.
- An earlier 2025 private-HOME startup attempt failed before reflection. Removing
  the borrowed application-wrapper alternate-loader/wait flags allowed the direct
  `wine start.exe /wait EXE PROJECT` route to reach exact sandbox readiness.
  Keep both attempts and avoid attributing causality to one individual flag.
- Native catalogs, source provenance and exact cross-host schema comparisons are
  being packaged and verified. #175 is not complete yet; #176 remains blocked.
- Supporting read-only research found additional observed object/plugin condition
  forms across all five installed builds, including integer sets/ranges, parent
  contexts, references and visibility. These remain #177/#178/#179 work, and the
  installed XML evidence does not substitute for live metadata or behavior proof.
- No Fresh run has been authorized or started for this specification.

Ignored durable coordination state is under `.waapi-skill-state/full-coverage/`:
`active-checkpoint.json`, independent `*-evidence-seal.json` files, original
capture roots, derived catalogs and the `research/` driver/source notes. Preserve
these before archiving worktrees. Every original failure remains unchanged.

## Standing completion rules

Every in-scope missing branch must receive implementation and required proof.
New gaps become same-parent implementation children and block final acceptance.
No family-level PASS, missing verifier, packaged limitation or unavailable local
prerequisite substitutes for proof. Keep native absence and approved exclusions
separate. Preserve three policies, config binding, closed inputs and one-shot
transactions. The two new Authoring ui.cli Lua/launch additions remain excluded.

Use TDD at the approved public Gateway/maintainer CLI seams, Poetry via ci/test.sh
for development tests, Skill-local Python for native/formal runtime, owned
sequential Wwise sessions, and separately approved small Mac-only Fresh batches.
Preserve ignored evidence before archiving any worktree. Final acceptance needs
all branch obligations, combined gates, native proof and Standards/Spec review.
