# Full WAAPI coverage implementation checkpoint

Parent: [Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).
User approved publication and implement-spec on 2026-10-17. The persistent Goal
is active. Integration branch: `codex/full-waapi-coverage`; base: merged PR #173
at `07c20232`. Do not merge main without a later explicit user request.

## Task graph

All 21 English tickets (#175–#195) are published as native sub-issues; all
36 blocking edges were verified. The proposal JSON preserves exact mappings.
The implementation frontier starts with #175 (native catalogs), then #176
(completion and ownership), then the unblocked functional slices. Close a child ticket only after its implementation is integrated and its own
acceptance evidence is complete, with an English evidence comment, so native
blocking edges expose the next frontier. Keep the parent open through incomplete
implementation and final acceptance; the draft PR carries the normal closing
references. No main merge is authorized.

## Active work

- Draft integration PR: [#196](https://github.com/zcyh147/waapi-skill/pull/196).
- #175 is complete and closed. Integration candidate `faa704ff` passed the fixed
  five-version Program gate: **7014 passed, 3 native-Windows-only skips**, exit 0,
  in 496.88 seconds. Final focused validation passed 140 tests. Original earlier
  stale-seal failures remain recorded separately.
- Ten independently attested Console/Authoring catalogs, full definitions and
  exact shared-schema comparisons are packaged. All 782 shared schema pairs
  match; all 48 initially missing ordinary Authoring schema rows are included.
  See [native collection](NATIVE_COLLECTION.md) for builds, provenance, original
  failures, offline derivation and separate cleanup follow-up evidence.
- #176 is complete and integrated at `cd9ccae07`. The evidence-driven checker
  passed the focused 66-test baseline and subsequent affected guard checks;
  the final-candidate preserved selection passed 9 tests. Post-merge `--check`
  exited 0 with structural consistency; product completion remains false.
  [Ledger usage and evidence contracts](LEDGER.md) guide the functional tickets.
- Active implementation frontier: #177 (conditions), #181 (queries/metadata) and
  #188 (Authoring layouts/views), in separate worktrees. Working agents now use
  GPT-6.1 Sol with high reasoning, as explicitly requested; root owns decisions,
  integration and native scheduling. #180 remains
  blocked by #178; do not infer readiness from family proximity.
- Read-only object/plugin condition research is retained for #177/#178/#179.
  It includes integer enums/ranges, parent contexts, reference requirements,
  visibility, Uint16 plugin conditions and expanded 2025 EQ conditions. Installed
  XML facts still require matching live metadata and behavior evidence.
- Five sequential Console condition-metadata captures on frozen `e0f2d295`
  completed: 37 targeted field details through 101 public Gateway calls. All
  five source full hashes and project mtimes were unchanged, successful sandboxes
  were removed, and no owned Wwise process remained. These establish native
  metadata shapes for #177/#178/#179; they are not edit, Authoring or Fresh proof.
  Exact receipts and independent seals are under the ignored coordination root
  in `condition-metadata-2021-r1` through `condition-metadata-2025-r1`.
- No Fresh run has been authorized or started for this specification.

## Functional implementation and native observations

The following are partial implementation checkpoints, not closed tickets or
final integrated acceptance:

- Integration `d9431c70` includes exact #177 `f8a2b7fc`, #181 `8f372491`
  and #188 `9e8d0847` partials. Existing-object condition planning, bounded
  metadata discovery and query projections, seven Authoring layout reads and
  scoped layout switching are integrated. The combined focused run passed
  **1530 tests**. Subsequent artifact checks preserved all **272,313** original
  native obligation identities, shapes and owners; no route was removed.
  Sixteen new public layout version rows retain #188 ownership without
  inheriting historical completion seals. No new verified branch or native
  effect credit is claimed.
- The full five-version Program run on `d9431c70` **failed**: **7416 passed,
  15 failed, 3 native-Windows-only skips**, exit 1, in 907.75 seconds.
  The original log and byte-sealed result remain in
  `program-d9431c70-r1.log` and `program-d9431c70-r1-result.json` under the ignored
  coordination root. #177 owns two historical source-equivalence fixture
  failures; #181 owns five query/protocol/reference-budget failures; #188 owns
  eight layout contract/catalog/inventory expectation failures. Their repairs
  and later passing runs must be recorded separately. This run is not a pass.
- Second integration `1bcaeeba3f03c50ca819fe64e03880542e3c8f81` merged exact
  #177 `65d7be41`, #181 `6b5ddae4` and #188 `bf69ec09` partials. The combined
  focus passed 1093 tests; one product-capture prerequisite error was retained
  until generated artifacts were reconciled. On the clean reconciled candidate,
  the exact product node passed separately and 64 artifact tests passed. Its
  separate product receipt proves one exact program branch only; required native
  evidence is missing, and the default ledger remains incomplete. The retained
  65 and 1bcaeeba receipts grant no proof to later source candidates.
- The fixed five-version Program gate on exact clean `1bcaeeba` **passed**:
  **7681 passed, 3 native-Windows-only skips**, exit 0, in 1036.40 seconds.
  `program-1bcaeeba-r1-result.json` seals the original log SHA-256
  `b4098b253967e2092a2536a427321c7b9a03ec8d1caed0ccd5346f6b38130062`.
  The owned process group was empty and source remained clean afterward. The
  three skipped native Windows checks grant no Windows execution evidence.
  This is candidate-specific Program proof, not full functional acceptance;
  the original `d9431c70` failure remains unchanged.
- Third partial integration consumes only #177 `3ba15e5e`, #181 `59fa22b7`
  and #188 `5ded219b`. It adds recursive satisfied association-owner condition
  guards, exact discovered-token binding for optional native metadata names,
  certified reference restrictions with absent type, explicit unavailable scalar
  type diagnostics, bounded Media Pool field-name discovery, scoped view
  get-or-create and 2025-only asynchronous close verification. No owner write,
  raw input route or broader native definition interpretation is introduced.
  Combined source validation passed **2062 tests**, with the exact product
  capture intentionally excluded. The artifact run passed 65 tests and retained
  one old route-count assertion failure; after synchronizing the exact getFields
  fixed-route count, its entire 17-test registry file passed separately.
  The 272,313 native ID/shape/owner tuples and historical seals remain unchanged;
  three newly linked view version rows grant no verified or native effect credit.
  All three tickets and their exact branch/native obligations stay open. No
  product receipt is recaptured or inherited for this successor.
- Full Non-live on exact clean third integration `f8f3a9ab` **failed**:
  **19324 passed, 15 failed, 127 skipped, 41 deselected**, exit 1, in
  1923.11 seconds. The original `nonlive-f8f3a9ab-r1-result.json` seals log
  SHA-256 `32d20e9ad2ca12d18912f92ad48bf3b6b43996fd01fa5b1553107adcf7319bf5`
  and empty owned-process state. Two notice-discovery consumer failures belong
  to #177; twelve query, Media Pool and documentation failures belong to #181;
  one fixed Program manifest count/order expectation needs integration repair.
  Preserve this FAIL separately from later focused repairs and broad gates.
- Fourth partial integration adds strict condition enum and live master-bus
  visibility checks through post-execution verification; exact existing-plugin,
  Parent and association program fixtures; original native-producer atomic
  publication controls; exact Media Pool field mappings and return-only fields;
  structured Short ID selectors for 2022.1–2025.1 with an explicit unresolved
  2021.1 boundary; scoped undock with independent optional coordinates; and
  shared Authoring lifecycle/producer/consumer controls after final teardown.
  Authoring launch strategy, native Windows resource attestation and full
  cross-family ownership remain incomplete. These fixtures are not launch-ready.
  Original candidate-specific product receipts are not transferred to this
  successor. All #177/#181/#188 implementation and native proof obligations
  remain open; no new native execution or completion credit is claimed.
- New Authoring launches are on hold after the user reported repeated access
  permission prompts. Continue implementation and pure-code validation; group
  remaining GUI effect tests on a frozen integrated candidate and explain the
  required interaction before scheduling. API/schema collection is complete;
  behavior and effect validation remain required. No native or Fresh run was
  started during this integration. Two obsolete read snapshot worktrees were
  archived after confirming that their only ignored files were disposable
  runtimes/caches; all original capture evidence remains in the coordination
  root.

- #177 candidate `5d899f1e` passed 487 focused program tests. Its separate
  native Show-condition probes passed both Self and Parent cases on all five
  pinned Console builds: 10 passing nodes. For GameParameter.SlewRateUp and
  Sound.Weight, both tested prerequisite values left the field enabled; writes
  succeeded without changing the explicitly selected prerequisite. All source
  full hashes and project mtimes stayed unchanged, all passing sandboxes were
  removed, and no owned process remained. The 505 sealed source files stayed
  unchanged during the sequence. Original pre-native fixture/configuration
  failures remain retained; they grant no native credit.
- These condition probes establish the sampled Show semantics. They do not
  complete all condition grammar, plugin applicability or branch-ledger native
  effect receipts. Original observations and independent evidence seals are
  indexed by `condition-show-native-summary.json`. Subsequent dependency fix
  `52579af7` removes the inaccurate blanket requirement that existing-plugin
  condition handling wait for new plugin creation work; all exact obligation
  identities, owners and unresolved evidence remain intact.
- #181 progress candidate `bd23a024` has 703 focused passing tests for metadata
  listing, detail pagination, useful field summaries, generated continuations
  and large-field acquisition. Query, Media Pool, peaks, result alternatives
  and exact branch evidence remain active work.
- #188 early read candidate `0afd7004` exposes five bounded Authoring reads.
  Root captured them on both pinned 2024.1 and 2025.1 Authoring builds through
  the public Gateway: 10 schema/read invocations per host, original source
  hashes and mtimes unchanged, clean owned-process shutdown and stable frozen
  source. `layout-read-native-summary.json` indexes original responses/seals.
  The Designer observations establish actual read serialization, including
  childless Splitter rows and repeated identical view identities. Several
  reflected definitions disagree with these native responses. This is not
  setLayout input acceptance, a mutation effect, or complete layout coverage;
  closed constructors, scoped identities and write verification remain #188.

The two Authoring capture roots retain their private runtime directories with
their original evidence. No owned Wwise process remains. All three working
branches are released from their capture freezes and continue implementation.

Ignored durable coordination state is under `.waapi-skill-state/full-coverage/`:
`active-checkpoint.json`, `program-faa704ff-result.json`, independent
`*-evidence-seal.json` files, original capture roots, derived catalogs and
`research/` notes. Preserve these before archiving worktrees. Original failed
roots and verdicts remain unchanged. No owned native process remains running;
unrelated pre-existing Wine helpers are never terminated by this work.

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
