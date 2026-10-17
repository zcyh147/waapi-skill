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
  Combined source focus on clean `e3637a2e` passed **2600 tests**, with one
  native-Windows-only skip and twelve intentionally excluded product-capture
  parameters, in 639.62 seconds. Source stayed clean and its owned process group
  was empty afterward. Original f8 Non-live FAIL remains separate. Condition
  native fixture success cleanup still occurs before final teardown; #177 must
  reuse the deferred-success lifecycle API before that fixture can launch.
  Producer publication rejection alone does not solve sandbox retention.
  Reconciliation derives **874 public version rows / 216 unique URIs**. Only
  2024.1/2025.1 `undockView` route keys are added; forty native obligations move
  from missing implementation to unresolved. Every original native ID, shape,
  owner, independent catalog seal, definition file and historical family seal
  stays unchanged. All 25 layout rows retain migration-required #188 ownership.
  Artifact validation retained **66 passed / 1 failed** for a stale Authoring
  special-route counter. After updating only the derived counters and retaining
  exact versioned undock membership, the entire 17-test Registry file passed
  separately. The first artifact FAIL remains preserved.
- Exact clean fourth integration `a0c192d9` passed the fixed five-version
  Program gate: **8356 passed, 3 native-Windows-only skips**, exit 0, in
  1443.43 pytest seconds (1446.83 wall seconds).
  `program-a0c192d9-r1.result.json` seals the unchanged source, empty process
  group and original log SHA-256
  `d9236654a2710d91078d121d45271d6c46d9d844a359ee0ab1c208b487b53237`.
  The skipped native shell, Python locator and NTFS junction checks grant no
  Windows execution proof. This gate predates the selected-metadata drift
  guard below and does not certify the successor or complete functional scope.
- Fifth partial integration consumes only #177 `6902c70f`, #181 `7d9018e8`
  and #188 `cd1363ec`. It adds recorded range controls and defers successful
  condition sandbox cleanup until actual final pytest reports, preserving
  publication failure separately from native/node failure. Both peak routes
  expose bounded decoded/raw/header fragments with exact repeated-result
  continuation checks; native response/time ceilings stay enforced. Oversized
  metadata names/types remain recoverable through scoped live selections and
  raw detail pages. Every ordinary selected property/reference seals normalized
  and original raw metadata before execution and during verification, including
  reference clear; absence and explicit null remain distinct. The existing
  lifecycle/driver now has fake-tested owned Mac Authoring strategy and exact
  collection hookup for five owner-aware layout nodes. No installed tool,
  Authoring, Console, native client or Fresh process was launched.
  Native Windows ownership, cross-family support, full remaining native/layout/
  query/metadata/peak branches and all exact evidence requirements remain open.
  No old product receipt is forwarded; earlier failed producer roots retain
  their original verdicts. This partial grants no native or completion credit.
  Combined source focus on exact clean `5b87ae32` passed **2689 tests**, with
  eleven Windows cmd.exe parity skips and six intentionally excluded product
  capture parameters, in 282.25 seconds. Source/head stayed clean and unchanged,
  and its owned process group was empty afterward. The new guard is covered by
  this focused run; a0 Program proof remains attached to the earlier candidate.
  The single remote-verified #183 Definition Short-ID acceptance item is synced
  locally as an open version-proof inconsistency, without a runtime change or
  native failure/absence claim. Existing ticket text and dependency are retained.
  Source reconciliation preserves all 874 route keys and all 272,313 native
  ID/shape/owner tuples, original definitions, independent catalogs, detailed
  policy and historical family seals. There is no branch-state transition or
  new verified/native/Fresh credit; all 25 layout rows stay #188 migration work.
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

- Sixth integration partial merges only #177 `f72f37df`, #181 `f7dd0f4f` and
  #188 `be48b1b1` onto `dcf0ae11`. Bounded complete condition closure, explicit
  standalone scalar capture admission, lossless large-query delivery/contextual
  failures and partial nested layout/dock/splitter controls remain unfinished
  overall. The original dcf0 full Nonlive result remains **19940 passed, 1 failed,
  127 skipped, 41 deselected** in 2382.44 seconds. Its sole platform verifier
  fixture failure is repaired by #181 with the missing independent metadata
  response; separate worker shared/platform validation passed **315 tests** in
  45.12 seconds. These are distinct candidates/runs, not a regraded broad PASS.
  Original f72 pure-code scalar batch passed five nodes in 558.46 seconds, covering
  995 groups/5202 exact members; this evidence stays on its original source and
  grants no integrated/default-ledger/live/native credit. Its strict reader
  independently matched all 5202 reviewed member IDs; every program result is
  implemented_unverified, all native/live_metadata proof remains missing and
  completion stays false (reader SHA-256
  `87a7a549d391f29533e9d4b1f41df65d6edb477cb40fdba9de82394fdd3a6f47`).
  All 467 unresolved
  source alternatives remain open. The new #193 WAL delivery and #194 larger
  terminal-response acceptance criteria are synced additively and remain open.
  Original failed roots, native requirements and historical evidence are retained.
  No native/Authoring/Console/Fresh launch or completion claim is made.
  Combined source focus on exact clean `8dfdcc76` retained **4134 passed,
  2 failed, 1 setup error, 11 Windows skips and 18 intentional deselections**
  in 1356.13 seconds. The failures were two stale exact layout-route assertions;
  the setup error was the generated route partition awaiting four new layout
  rows. Original run/source/exit remain sealed; reconciliation and targeted
  reruns are separate evidence. The additional #193 tone empty-collection
  criterion is synced as open work, with no runtime expansion.
  Reconciliation derives 878 route rows and 218 unique URIs; exactly four
  2024/2025 dockView/moveSplitter keys are added. All 272313 native ID/shape/owner
  tuples, independent catalogs, original definitions and historical family seals
  remain unchanged. Sixty-four missing-route obligations move only to unresolved;
  all 29 layout rows remain migration_required under #188.


- Seventh partial integration consumes only fixed #181 `b95bddbb`, #177
  `7ed7a105` and #193 `c253c5ae`. Exact discovered-type selections now enter
  bounded object queries with inventory/endpoint/build/session/expiry binding;
  reference target hierarchy checks use the exact current or explicitly declared
  controlling reference, retaining unknown classifiers as unfinished work.
  Tone WAV verification independently checks owned artifacts and reports active
  waveform, populated-marker and native representation gaps explicitly; legal
  empty channels/markers remain distinct from omission. The shared regular-file
  opener retains existing source-proof callers and bounds hashing to the initial
  extent. No native/Authoring/Console/Fresh process was launched.
  Reconciliation retains 878 public rows / 218 unique URIs and all 272,313 native
  ID/shape/owner tuples, ten independent catalogs, five original definitions,
  detailed native policy and historical completed-family seals. There are no
  route additions/removals, coverage-state transitions or new native/Fresh credit.
  The actual Program union has 241 unique nodes without file/node overlap.
  #194 now explicitly owns missing layout Draft taxonomy and the broader exact
  command/event replay policies; the larger Tone terminal gap remains #193 work.
  Original worker runs, r6 failures and original scalar evidence remain bound
  to their original candidates. Focused validation on clean `9cfa110f` retained
  **372 passed, 1 failed and 11 Windows-only skips** in 157.38 seconds, exit 1;
  the sole failure was a stale aggregate operation-schema seal after the five
  `object.setReference` guidance changes. No runtime changed after that run.
  Exact seal repair `b1fadd6e` restores the original aggregate by reverting only
  those reviewed words and preserves the earlier layout-proof seal; its entire
  affected digest file passed **16 tests** in 0.31 seconds, exit 0. Both original
  results and empty process-group receipts remain separate. Full Program and
  Non-live gates remain pending on the final integrated candidate.

- Eighth partial integration consumes only fixed #177 `6ae226a8`, #193
  `02c8f2d0` and #194 `6a05ce99` on `b328ec63`. Existing-object reference
  category/playability and shared-owner checks retain exact live facts, one-shot
  execution and terminal false-versus-unknown verification outcomes. The opt-in
  GameParameter source plan maps 35 exact original Min/Max members through ten
  direct receiver groups; its default approved f72 plan and all native/live
  requirements remain unchanged. WAL responses preserve the complete native
  document through bounded context-bound fragments, and large legal Tone plans
  retain bounded request/artifact checks. The Program Tone fixtures now create
  independent isolated WAV artifacts. Formal-harness compatibility uses actual
  public Draft continuations and compact terminal receipts; compound-child and
  remaining #194 acceptance work stay open.
  Reconciliation preserves 878 public rows / 218 unique URIs, all 272,313 native
  ID/shape/owner tuples and all obligation states, requirements and evidence.
  Three WAL command contracts and fourteen named metadata contract seals change;
  parser and continuation seals follow the reviewed runtime. The Program union
  remains 241 unique nodes without duplicate or whole-file/node overlap.
  Original b328 Program **9495 passed, 3 failed, 3 Windows skips** in 2398.60
  seconds remains a FAIL, independently of the repaired Tone fixture evidence.
  Worker #194's original synthetic-fixture failures remain preserved; its fixed
  four-module focus passed **742 tests with 6 native-Windows skips** in 371.31
  seconds. Combined integration focus on clean `8a87aa3e` passed **1488 tests
  with 5 intentional scalar-product capture skips** in 545.81 seconds, exit 0.
  All 1801 tracked file hashes remained unchanged and the owned process group
  was empty afterward. This focused run covers the merged public compatibility,
  metadata, WAL, Tone, route matrix and derived-contract seams; full Program and
  Non-live gates remain pending. No native,
  Authoring, Console or Fresh process was launched for this integration, no
  historical receipt is transferred, and no ticket completion is claimed.

- A separate successor integrates only #177 `4fb0dde3` after the eighth partial
  checkpoint. Repeated or mixed target restrictions admit an existing object
  only when fresh exact-ID facts independently satisfy every disclosed row;
  partial matches retain the explicit boundary. Classifier reads deduplicate
  fields, preserve selected platform and reject native type drift. This is a
  sufficient program condition, not complete native combination semantics.
  The affected hierarchy, activation and registry tests plus generated-interface,
  parser and Program-roster controls passed **758 tests** in 101.76 seconds on
  clean `7bc68aa0`, exit 0. All 1801 tracked file hashes remained unchanged and
  the owned process group was empty. Interface and branch-ledger reproducibility
  checks passed. Reconciliation changes only the registry source seal/index and
  coverage candidate identity; native obligation identities, shapes, owners,
  states, requirements and evidence remain unchanged. The earlier eighth-partial
  result remains separate. Full Program/Non-live gates and all native acceptance
  remain pending; no native or Fresh process was launched.

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
