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
- Current work covers remaining new-object conditions and graph effects
  (#178/#180), Console project/artifact behavior (#184), Authoring layout
  semantics (#188), bounded diagnostics (#193), and exact evidence attachments.
  Root owns integration, native scheduling and final acceptance. Only #175/#176
  are closed; partial implementation and passing individual cases do not close
  the other tickets. Every new subagent uses `fork_turns="none"` with only the
  necessary task context.
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

- Ninth partial integration merges only #184 `57468391`, #193 `67e7ee7c`,
  #194 `3a3a1aac` and retro `603d0f7b`. Saved-project observations, Tone marker
  and anonymous-header checks, and exact multi-root/cleaned-input archive replay
  remain partial implementation with native acceptance open. A narrow matrix
  fixture RED (8 failures) and repaired GREEN (8 passes) remain separate.
  Clean `f6adb041` passed the central preflight **825 tests in 22.01 seconds**
  and its non-overlapping affected focus **494 tests in 191.01 seconds**; all
  1806 tracked hashes remained unchanged and both owned groups ended. A later
  public-seam platform-matching regression preserved **3 failed / 3 passed**,
  then **6 passed in 3.28 seconds** after matching named constraints before
  base-only rows. Those results are separate from the earlier candidate.
  Reconciliation preserves 878 routes, 218 URIs and all 272,313 native obligation
  IDs/shapes/owners/states/requirements/evidence; the Program roster is 242 unique
  nodes. Full gate selection remains Root-owned. No native or Fresh launch,
  ticket closure, historical evidence transfer or main merge occurred.

## Tenth combined source checkpoint

The fixed combined inputs are #178 `d7f11bbd` and #189 `fa97c305`, the latter
already containing #187 `2506eb31` and integration `a8f86530`. The earlier #177
closure and two #184 increments remain included. Class/default planning and
root-only staged repair, bounded Topic event handling, and owned Authoring
window/model/signal contracts remain partial implementation. No native, Fresh,
Windows or whole-ticket completion is inferred from these fake-client changes.

Reconciliation adds exactly eighteen 2024.1/2025.1 model function rows, yielding
896 public version rows / 227 unique URIs. Their exact native schemas remain in
the immutable model supplements; referenced WAFM definitions resolve through the
original independent Authoring graph. A separate #189 migration group prevents
historical host/UI family credit. All 272,313 original native identities, shapes,
owners, requirements and evidence remain intact. Exactly 1,753 obligations move
from missing implementation to unresolved because the public routes now exist;
none receives verified/native credit. Ten catalog seals, original definitions,
detailed selector rules and historical completed-family seals are preserved.
The actual Program roster is 247 unique nodes, including all four newly added
public test files, without duplicate or whole-file/node overlap.

The first branch-generation attempt stopped on the retired GameParameter-only
compiler symbol; current source pointers now name the generalized class compiler.
The original failure is retained separately. An earlier preparatory surface build
also exposed missing WAFM reference reachability and stopped before publication;
linking the original independent Authoring definition graph resolves that gap.
On exact clean `c689fd05971ed75425900713e50c3c3d5eac6ce5`, one central
preflight passed **825 tests in 22.40 seconds** and the non-overlapping combined
selection passed **39 tests in 303.16 seconds**. Both runs preserved all 1,817
tracked file hashes and ended with no owned processes. Sequential interface,
branch and release-report `--check` commands also exited zero. Original results
are sealed in `integration-partials-r10/FINAL-RESULT.json` under the ignored
coordination directory. Worker results retain their original candidates and
verdicts; the coordinated two-version signal check on `24dab99f` was not
repeated. No full Program/Non-live, native or Fresh acceptance is inferred.

The next full Non-live gate is scheduled after the fixed #179/#185 integration,
with duration reporting, so these related runtime changes share one settled
milestone. There is no automatic repeated Program gate or native/Fresh launch.

## Eleventh through thirteenth integration checkpoints

R11 froze `593877b2bb17f8a23c9ba636fa39b8b063f297f4`. Its central preflight
passed **825 tests in 21.50 seconds**; the single full Non-live run retained
**62 failed / 21,782 passed / 132 skipped / 41 deselected in 4,567.49 seconds**.
All 1,820 tracked hashes remained unchanged and its owned process group ended.
This remains the latest completed full Non-live result, not a whole-gate PASS.
The original 62 failures divide into forty plugin metadata fixtures, sixteen
contract/evidence/reference fixtures, and six compact-output test functions;
repairs and their focused proofs retain their own candidates below.

R12 reconciled the fixed object graph, Console artifact, runtime/shared schema,
2022 reference-array and compact-output inputs. Central preflight on `b12db6c9`
retained **790 passed / 35 failed in 30.22 seconds**, following an earlier
external developer-environment collection block (exit 4). Console fixtures
retained an initial failure at `89cea4bd`, then **35 passed in 2.37 seconds** on
`1db0d7dc`. That candidate's crossfocus retained **43 passed / 1 failed in
13.08 seconds**, followed by only its unexecuted independent remainder:
**122 passed in 67.29 seconds**. These are separate selections, not a combined
all-green run. After the 2022 schema correction, `c538d104` passed the affected
**8 tests in 0.93 seconds** and the sixteen original triage nodes in **1.43
seconds**; two obsolete-node collection errors remain recorded. Final
`db57c484fdc69bd92c7ef92c9d869858cc3d775b` passed the six original output
functions (**10 tests in 11.42 seconds**, including five SoundBank versions).
Its 1,829 tracked hashes remained unchanged and owned processes ended.

R13 combines Short ID source/Definition contracts `a32b2c71` and explicit native
pytest-selection fixes `07b6a4d0` / locked coverage-option successor `45fcb03c`.
The five-version source evidence supports bounded typed Short ID reads; public
Definition processing remains 2022.1–2025.1. Numeric Short ID, canonical GUID,
type and later role drift checks remain independent. Driver tests use injected
runners only; they provide no native execution evidence. Sequential interface,
branch and release-report checks passed after preserving an initial stale
branch-fingerprint check failure caused by final reference pruning.

Central preflight on exact `21d2c248ba55e7d2ad56a74bf754aa043fc2fb07` retained
**821 passed / 4 failed in 21.76 seconds**. The four inherited matrix fixtures
incorrectly required filesystem-effect metadata for `cli.verify`, whose
contract exposes only the documented process outcome. Test-only successor
`4ce17e5de020a13909641738099edf73d4c62def` explicitly preserves that weaker
boundary and passed one deduplicated crossfocus of **20 tests in 0.98 seconds**:
2021 query/schema, 2022 DialogueEvent Definition and Short ID role drift,
explicit live/destructive/matrix argument selection, coverage-option handling,
reference controls, and those exact four failures. Both runs preserved all
1,834 tracked hashes and ended without owned processes. No full preflight,
Program or Non-live rerun is inferred from the focused repair.

R12/R13 preserve 896 public rows / 227 URIs, the actual 251-node Program roster,
all 272,313 native obligation identities/shapes/owners/requirements/evidence and
historical seals. No native obligation receives PASS credit. Original logs,
failures, source hashes and process receipts remain in ignored
`integration-partials-r11`, `integration-partials-r12` and
`integration-partials-r13`. Native applicability, inline media compatibility
and the remaining same-parent obligations stay open; no smaller scope,
Fresh acceptance, ticket closure or main merge is claimed.

## Fourteenth integration and targeted native checkpoint

R14 `3b963f47571e2501809d42ea1a4bfc8239c05645` combines scoped inline WAV
compatibility, import target/language verification repair and owned-list probe
preparation. Its central preflight passed **825 tests in 21.79 seconds** and
deduplicated crossfocus passed **19 in 3.03 seconds**. All 1,834 tracked hashes
stayed unchanged, process groups ended, and all 272,313 native obligations kept
their identities, requirements and evidence. This is not another full gate.

Test-only `23ae9be2` shares Short ID reads with the existing workflow sandbox.
Its twelve fake controls passed, but the first 2021 native run exposed an invalid
inherited `--kind event` fixture command: **1 failed / 2 skipped**, retained.
Test-only `c98897e2` fixes discovery through the existing public custom-kind path
and passed **17 focused controls**, including the complete collector through the
actual five-version Gateway parser and injected native dispatch. No product
runtime changed between R14 and c988.

Frozen c988 targeted macOS results: **1 failed** on 2021, **1 failed / 1 passed /
1 skipped** on each of 2022 and 2023, and **2 passed / 1 skipped** on each of
2024 and 2025. Current inline WAV acceptance passed all applicable 2023–2025
versions, including Gateway verified state and independent exact media bytes.
Short ID observation passed 2024/2025 and exposed a DialogueEvent lookup gap
on 2021–2023. Owned-list observations remain incomplete; 2022 Curve metadata
observation passed. See [native follow-ups](NATIVE_FOLLOWUPS.md) for scope.
All 1,835 tracked hashes and source-project hashes/mtime stayed unchanged;
process teardown was clean. Failed/mixed-SKIP sandboxes remain quarantined.
Individual passes are not whole-lifecycle passes. No Fresh/Windows acceptance,
ticket closure or main merge follows from this checkpoint.

## Fifteenth and sixteenth integration checkpoints

R15 `7926e4fdab45885e2d23579708c1297148b0254b` combines remote-target
identity checks, source-file usage projections, scoped compound cancellation
observations and legacy native-default handling. Review found that cancellation
readbacks used the dispatcher's default byte ceiling instead of the selected
catalog contract. The public 300 KiB negative reproduced the error; `f8043c8d`
now applies that contract's 256 KiB limit and preserves incomplete observation
and rollback-false outcomes. Its exact negative passed separately. Final R15
preflight passed **825 in 22.08 seconds** and the combined focus passed **23 in
18.46 seconds**. All 1,837 tracked hashes stayed unchanged and owned processes
ended. These results do not establish provider effects or undo-history lifetime.

R16 `49f5e2f05c957506c6a6e8b1973b2a4e5112dc3d` adds the native-diagnosed
Short ID repair and effective compound property-platform binding. Omitted
platforms remain omitted in native requests; matching project context binds
their meaning where observed. Review reproduced null, unlisted, removed and
duplicate current-platform identities; `6af1b49a` requires a non-null GUID in
exactly one project-platform row before preparation and execution. Those four
negatives and the independent-platform positive passed separately. Final R16
preflight passed **825 in 22.10 seconds**, with **19 in 6.34 seconds** in the
deduplicated focus. All 1,837 tracked hashes stayed unchanged and owned processes
ended. Earlier-version and reference-specific platform gaps remain unfinished.

Both batches preserve **896 public version rows / 227 URIs / 251 Program roster
entries** and all **272,313** native obligation identities, ownership and
evidence. Neither assigns native ledger completion credit. Original failures
remain attached to their candidates. The latest completed full Non-live run is
still the R11 failure; focused repairs do not regrade that run.

## Repaired Short ID native observation

Read-only diagnostic candidate `f7c77edc` showed the same DialogueEvent on
2021–2023 failing an integer WAQL comparison while matching the equivalent
decimal comparison. GUID-only reads found the object; a signed conversion also
failed. The 2024 control accepted both the positive integer and decimal. This
supports the observed comparison difference, not an assumed internal overflow.

Repair `b347acfa570c8e51ac908d77eeb2ae68847aa7f4` uses equivalent decimal
rendering only for typed Short ID predicates in 2021–2023. The public uint32,
exact GUID/type checks, candidate limits, later typed routes and existing numeric
selectors stay unchanged. The original public Event/DialogueEvent observation
node then passed once on each of **2021.1, 2022.1 and 2023.1**, with exact GUID
and Short ID readbacks. All 1,835 tracked hashes and source-project hashes/mtimes
stayed unchanged; all three PASS sandboxes were removed and owned processes
ended. Prior 2024/2025 passes remain attributed to `c98897e2`; they were not
rerun on the repair. This is scoped lookup acceptance, not Definition mutation,
collision, whole-ticket, Windows or Fresh acceptance.

Original evidence remains in `integration-partials-r15`,
`integration-partials-r16` and the short-id worktree's `native-f7c77edc-r1` and
`native-b347acfa-r1` coordination roots. The original c988 failures remain intact.

## Seventeenth integration checkpoint

R17 staging `18370d99b0f227c23a7f5f57c62cc121c74537d0` combines Authoring
project creation/empty-close, exact object-to-source-control file scopes and
prospective new-object group/default references. Root and merger independently
reviewed the fixed inputs. The original central preflight on `95dd3fa9` retained
**800 passed / 25 failed in 27.27 seconds**. The failures exposed a shared
project-artifact observer assuming a URI in older generic snapshot plans.
The minimal fix preserves URI-free snapshots and uses the Authoring kind only
for an explicit Authoring creation URI. On the repaired candidate, the exact
25 failed nodes plus 17 non-overlapping checks passed: **42 in 15.10 seconds**.
The 800 original passes were not repeated; this is not a final-candidate
825-test PASS. Both runs preserved all 1,839 tracked hashes and ended with no
owned processes. The native ledger remains byte-identical to R16; no native
credit or ticket closure is claimed.

At the R17 checkpoint the full Program gate was still running on frozen R16;
its terminal result and later exact-node repairs are recorded below. R17 did not
replace that running checkout. No broad Non-live or Fresh rerun was started.

Follow-up fixed `6ad03726` adds bounded per-file getStatus reads and permits
them in read_only mode; its 27 focused checks passed in 3.98 seconds. It is not
yet integrated in R17. Fixed `5d7213cb` prepares Switch/State same-create native
acceptance and adds class-ID observations to the existing owned-list collector;
its separate 13-case focused slices remain preparation evidence. The subsequent
native run is recorded separately below.

## Eighteenth integration evidence checkpoint

On fixed `5d7213cbdd114dd7e9ab976f6493a272c91becd9`, both prospective
SwitchContainer creation families passed on every matching macOS Console version
2021.1–2025.1: **10 individual native PASSs**. Each created once with both group
and default references, then independently read back the root identity and both
references. The 2021–2024 lifecycles passed and removed their sandboxes. The 2025
run retained **2 passed / 1 skipped**: its additional owned-list observer stayed
incomplete, so the whole lifecycle remained SKIP and its sandbox quarantined.
All source-project hashes/mtimes/tree metadata and 1,837 tracked hashes were
unchanged; owned processes ended. These scoped results do not assign native
ledger completion or whole-ticket credit. See [native follow-ups](NATIVE_FOLLOWUPS.md)
for the observed class identity and remaining discovery gap.

R18 staging combines the fixed status reader `6ad03726`, provider profile
`8c781e34` and the test-only native preparation. Provider evidence is fake/public
Gateway and protected result-schema proof: native connection/credential values
stay transient, while the verifier remains `verified:false` and provider
identity/settings/effects remain unproved. No provider native or Windows privacy
acceptance is claimed.

The isolated 2025 named-template node passed once before and once after the
accepted per-call graph reuse repair: **29.16 seconds** on `d483d670` and
**22.40 seconds** on `a3821579`. This is one timing observation, not a general
performance claim. The earlier cProfile run's deadline TIMEOUT remains a separate
failure; its overhead may contribute. Four public schema-equivalence, fresh-byte
tamper and alternate-root controls passed; no cross-call cache, plan-validation
removal or deadline relaxation was introduced.

The original full Program gate on frozen R16 `49f5e2f0` terminated with
**11,763 passed / 14 failed / 3 skipped in 3,907.33 seconds**, exit 1. All 1,837
tracked hashes stayed unchanged and the owned process group ended. On R18
`ce9adba4`, just those 14 nodes retained 11 failures while the three 30 ms Topic
controls passed unchanged. Test-only repair `58f138a4` updates reviewed schema
and lifecycle-choice assertions, retained query guidance, valid saved-project
fixtures and post-cancel readback expectations. It gives three schema/matching
controls a one-second test budget while preserving deadline/cleanup negatives
and all production limits. The original 14 plus six necessary neighboring
controls passed **20 in 3.78 seconds** on that exact repair, with all 1,850 tracked
hashes unchanged and no owned processes. This is a focused repair result, not
a new full Program PASS.

R18 also includes fixed documented List discovery `c989fd14` and Sound/media/move
scopes `745213c2`: explicit source/language identities and bound move endpoints
remain revalidated before dispatch. Their worker selections remain on their
original candidates; provider effects and native list/write obligations remain
unproved. Sequential inventory generation and both structural checks preserved
896 public rows / 227 URIs / 251 Program roster entries and the byte-exact
272,313 native-obligation artifact, including historical owners and evidence.

The single R18 central preflight on `cb38ee6c` retained **822 passed / 3 failed
in 22.80 seconds**. The three provider matrix rows still synthesized native
arguments without the now-required private-profile proof. Test-only repair
`6a4a1af8` uses the existing public Draft helper and protects secret-bearing
results; it preserves schema-only verification, no provider-effect claim and
execute-once behavior. Those three exact rows plus 18 deduplicated cross-seam
controls passed **21 in 9.02 seconds** on that repair. The selection includes
the restored real-child platform/language guard, List class/path/owner checks,
prospective-reference collectors and source-control status/Sound/move boundaries.
Both runs preserved all 1,851 tracked hashes and ended without owned processes.
The 822 original passes and earlier 20-node repair were not repeated; this is
not a final-candidate 825-test or full Program PASS. No native or Fresh run was
started for this integration.
Original receipts are retained under
ignored `integration-partials-r18` and the query worktree's
`native-5d7213cb-r1` roots.

## Nineteenth integration checkpoint

R19 combines fixed name-only Language GUID resolution `06c91530`, complete compact
project snapshots `c6739d03`, exact observed Console result compatibility `8aef5e52`,
planned documented Lists `33b0c9f8` and the reviewed owner-field collision repair
`9ee53e9a`. The review found that an unrelated class List handle named Metadata
could capture MetadataSlot's scalar Reference of the same name. The public RED
and 13 focused controls remain worker evidence; the repair propagates only this
owner declaration's selected List fields with array targets. R18's restored real
child platform/language control remains unchanged. All original native format
runs remain FAIL; [Console media facts](CONSOLE_MEDIA.md) retain literal results
and source/receipt provenance without assigning effect credit.

Sequential reviewed seals, interface/branch generation and both structural
checks preserved **896 public rows / 227 URIs / 251 Program roster entries**,
507 current contracts, all historical seals and the byte-exact 272,313 native
obligations. R19 adds no native completion, absence claim or ticket closure.

The single central preflight on `8be8eb2b` retained **824 passed / 1 failed in
23.70 seconds**. Its newly added create-proof inverse reproduced the prior seal,
but a later historical null-reference check rebuilt the current contract and
reintroduced that proof. Test-only repair `e2905274` reuses the exact inverse
helper; all historical seal values remain unchanged. That exact failed node plus
20 deduplicated cross-seam controls passed **21 in 9.36 seconds** on the repair.
The focus includes Language GUID proof in bound moves with drift refusal, compact
media counts and duplicate preservation, narrow native-result acceptance/rejection,
protected provider validation and planned List/scalar/class/owner/order controls.
Both runs preserved all 1,852 tracked hashes and ended without owned processes.
The 824 original passes and worker whole selections were not repeated: this is
not a final-candidate 825-test or full Program PASS. Receipts and original worker
failures remain under ignored `integration-partials-r19`.

Root's separately completed hosted R18 run `39076934774` passed **825 in 50.47
seconds** on exact `1111f998`; it is independent of local R18/R19 results. R20
history/mapping and other moving work remain excluded. No native, Fresh or broad
gate was started for this integration.

## Twentieth integration checkpoint

R20 adds fixed latest-project-history `df79898a`, exact central media mapping
`715f5fba` and saved-baseline native preparation `3d05ddd1`. History receipts are
scoped effect expectations, never selectors for a native stack entry. Seven
pinned lanes use the closed business Draft with receipt integrity, runtime/project
binding, prewrite drift checks and independent scoped readback; native head
identity and effects outside that scope remain unobserved. The mapping verifier
retains exact source/language/file/MediaID multisets, empty Work Unit storage,
project mode and non-storage preservation; unknown containers remain unverified.
The collector saves its private sandbox through Gateway before taking its
independent baseline, requires business verification and retains failure bytes.

Integration review reproduced false verification for conflicting XML Value and
ValueList encodings in both project storage mode and plugin media filename. Four
runtime guard lines reject dual encodings without choosing precedence. The two
original public RED selections each retained **1 failed / 1 passed**; storage
controls then passed **2 in 1.32 seconds** on `18f739c4`, and plugin controls
passed **3 in 1.94 seconds** on `3172e35d`. Single attribute and nested encodings
remain accepted. These are separate candidates and overlapping controls.

Reviewed seals and serial interface/branch generation/checks preserved **896
public rows / 227 URIs / 251 Program roster entries**, all historical seals and
the byte-exact **272,313 native obligations**. Current registered contracts are
514. Removing only the five internal history-binding fields reproduces the prior
named-contract seal; no native evidence, requirement, owner or state was credited.

The single central preflight on `03451653` retained **818 passed / 7 failed in
25.70 seconds**. All seven failures were history matrix fixtures still supplying
unbound empty native requests. Test-only `40362f01` uses the existing public
owned-receipt Draft lifecycle, checks scoped verification, exact terminal result
and execute-once behavior. The seven exact failures plus 12 deduplicated
cross-seam cases passed **19 in 13.41 seconds** on that repair, including both
final collector controls. Both runs preserved all 1,855 tracked hashes and ended
without owned processes. No complete preflight rerun or final-candidate 825-test
PASS is claimed. Original logs and proofs remain under ignored
`integration-partials-r20`.

Root separately reported hosted R19 run `39078615568` passing **825 in 48.28
seconds** on exact `1e8cf27b`. Its later native 2025 attempt on fixed `3d05ddd1`
remains **FAIL**: exact central media rows and storage checks passed, while model
preservation failed. Representation-equivalence repair and later history work
remain outside R20. No native, Fresh or broad gate was launched by this merger;
program controls do not supply native effect credit.

## Twenty-first integration checkpoint

R21 combines fixed Console serialization and verdict messages `69d3439d`, optional
history expectations and scalar-property/ancestor observers `39b9fc4c`, separate
migrated-fixture preparation `bad546b1`, and same-graph result references
`d3184b8a`/`81a8f5f5`. R19 already contains `9ee53e9a`; it was not merged again.
Reference result handles remain prospective declarations until independent actual
GUID/class/parent/owner readback. Preview discloses proven free rename candidates;
execution rechecks their availability and the observed collision state. Native
rename policy remains intact. No same-graph native effect is inferred from fakes.

Without an optional history receipt, verification explicitly remains result-schema
only, with no observed stack head, effect or preservation. A selected invalid or
changed receipt never falls back to that weaker mode. Typed scalar-property
expectations refresh metadata and bind the original explicit platform GUID;
current/named-platform certification and other observers remain implementation
work. Compound ancestor paths derive from sealed hierarchy segments.

The suspected Console message issue from the merger's initial trace was disproved
by the existing `VerificationResult.__post_init__` guard. A public preservation-
failure summary regression passed **1 in 1.02 seconds** on `8e4827e6`; no product
RED or redundant runtime repair is claimed. R20's dual-encoding guards and prior
current-platform, provider, callback and URI-free observer fixes remain intact.

Reviewed seals and serial interface/branch generation/checks preserved **896
public rows / 227 URIs / 251 Program roster entries**, 514 current contracts and
the byte-exact 272,313 native obligations with original owners/requirements/states.
The exact create result-binding inverse reproduces the prior named-contract seal;
all historical seals remain checked. On frozen `01b63248`, the single central
preflight passed **825 in 27.61 seconds**, and the proportional cross-focus passed
**20 in 13.25 seconds** with `--durations=20`. Both runs preserved all 1,856 tracked
hashes and ended without owned processes. The focus covers migrated/direct
collector ordering, serialization negatives, optional/property/ancestor history,
new-reference identity/metadata drift, 2021 create, controlled rename, planned
hierarchy, scalar/List separation and the real child effective-view guard.
Whole worker 55/65 selections and broad gates were not repeated. Original worker
REDs and receipts remain in ignored `integration-partials-r21`.

Root's exact `69d3439d` native direct case passed only on 2025.1; 2021.1–2024.1
remain FAIL despite matching media mappings and storage mode because other saved
model content changed. The separate `bad546b1` migrated 2023 case also remains
FAIL: migration closed the project, so the new media Draft stopped at
`getProjectInfo` before its target write. Migration preparation has no effect
credit. The later lifecycle-reload fix `76a7efc6`, ledger capture and moving worker
successors are outside this batch. This merger launched no native/Fresh or full
Program/Non-live gate; these results do not close any ticket or transfer native
acceptance to R21.

## Twenty-second integration checkpoint

R22 fixed candidate `81318aea` adds attested Console open/create from the exact
native no-project state on 2023.1–2025.1. Opening seals the selected saved
project GUID/name/file proof and verifies the actual live identity and path;
transport errors never establish project absence. The first Draft declaration
binds the current runtime even without a loaded project. Other operations and
2021.1/2022.1 do not inherit this exception.

Original central preflight on `84457fa6` remains **822 passed / 3 failed in
28.78 seconds**. Three old matrix fixtures supplied nonexistent project files;
test-only `81318aea` supplies actual saved project proofs. Those exact failures
and adjacent checks passed **19 in 7.40 seconds**. Separate five-version media
capture plus the strict evidence reader passed **6 in 38.51 seconds**. All runs
preserved 1,857 tracked hashes and ended with no owned processes. No unchanged
whole preflight or broad gate was repeated. R21 hosted preflight on published
`1914dcdc` independently passed **825 in 54.79 seconds**, run `39080755597`.

Media captures now retain actual public requests, injected native calls and
setup/call/teardown outcomes. Original native `69d3439d` evidence passes its own
source context but is rejected as current-native proof because runtime sources
changed. Default 272,313 obligations, owners and requirements remain unchanged;
the five exact result-schema attachment rows grant no family-wide completion.

Root native attempts retained three prewrite new-reference failures: `1c4924d6`
used an old hierarchy alias; `cef6d183` selected neighbouring fields via fuzzy
discovery; `49b176e1` correctly selected UserAuxSend0 but exposed an unsupported
new-object class condition. No target write occurred. The first two fixture
repairs do not resolve the third product gap; its implementation remains #180.
The migrated media setup still needs its public Console-open continuation and
matching native proof. No Fresh, final broad-gate PASS, ticket closure or main
merge is claimed.

## Twenty-third integration checkpoint

R23 tested code candidate `49de1610` combines complete bounded exception keys
`17a3797f`, exact native field selection `49b176e1`, and the closed 2025 Authoring
reset route `40dc03e9`. Review reproduced a further error-envelope failure:
a 5,001-digit integer metadata key raised during formatting and discarded all
optional metadata. `110b0cf7` omits only that unformattable key with the existing
explicit marker. Original public RED passed separately after the narrow repair.

Reset preserves native omission, empty and ordered repeated selections. It
revalidates the live instance, actual selections and catalog, follows all three
policies and executes once. Its bounded post-observations are deliberately
schema-only: independent default-state effects and preservation remain required
under #188. The source catalog establishes this exact URI only for 2025.1.

Actual generated scope is **897 version rows / 228 unique URIs / 515 registry
contracts / 32,978 public schema branches / 251 Program entries**. Exactly 17
original reset obligations change from missing implementation to unresolved.
All 272,313 native IDs, shapes, owners, requirements and evidence remain intact;
there are 272,197 unresolved and 116 approved exclusions, with no new verified
credit. Three pre-existing getStatus policy snapshots now reflect their already
implemented read route. All serial generation and check modes completed.

On frozen `49de1610`, the single central preflight passed **825 in 28.68 seconds**;
the deduplicated cross-focus passed **29 in 95.07 seconds**. Both preserved all
1,857 tracked hashes and left no owned processes. `6713c636` only joins the
published documentation ancestry and has the identical tree; no test replay or
new acceptance identity is inferred. R22 hosted run `39082237238` independently
passed **825 in 53.76 seconds** on published `09c73a72`.

Separate pending work remains outside R23: `0d8d496a` narrowly normalizes empty
Bus ReferenceList serialization, with 16 focused passes and a matching 2022
native media PASS (11.25 seconds). Source hashes/mtime/tree were unchanged,
PASS sandbox removed and processes cleaned. The separate migrated-media fixture
at `185355a8` now uses a public reopen transaction, but matching 2023 native
execution failed before dispatch: Wine path adaptation required an open-project
anchor even though this operation starts from no project. Original failure and
quarantine remain; the runtime repair stays #184. New Bus/AuxBus condition code
`5341f545` has 51 focused passes but still needs actual controller metadata and
same-graph native effects. None of these results closes a ticket or transfers
native credit to R23.

## Twenty-fourth integration checkpoint

R24 fixed code `55383f8c` integrates prospective Bus/AuxBus structural conditions,
empty Bus reference-list and scalar/RTPC serialization preservation, separately
authorized project reopening after migration, and the existing guarded Wine
none-to-target mapping for Console open/create on 2023.1–2025.1. The merge keeps
both noisy field discovery and native-condition controls, including one public
case exercising both. The new Bus condition test file is explicitly included in
the fixed Program roster, now **252 entries**. No native obligation identity,
owner, requirement or evidence changed; v1 evidence reuse remains byte-strict.

On unchanged `55383f8c`, central preflight passed **825 in 26.75 seconds** and
the proportional integration focus passed **27 in 11.88 seconds**. Both sealed
1,858 unchanged tracked hashes and zero owned processes. The subsequent full five-version
Program gate ended with 12,245 passed, 168 failed and 4 skipped (4,131.32
seconds); its original failure remains unchanged. No full Non-live or Fresh rerun was started.
R23 hosted run `39082897954` independently passed **825 in 57.63 seconds** on
published `3e3a31ec`.

The R24 native 2023 migrated-media lifecycle remains **FAIL (10.82 seconds)**.
Its new reopen step did execute once and strongly verified saved/live project
GUID, name and path. The later media write preserved all 734 exact mappings and
storage mode, but the independent non-media preservation assertion failed. This
is progress through the former prewrite gap, not a whole-lifecycle PASS. The
2025 same-graph reference case remains **FAIL (8.86 seconds), before any write**:
the real AuxBus class exposes a UserAuxSend0 override dependency but rejects
metadata for OverrideUserAuxSends because that property does not exist on the
class. Previously simulated Boolean controller metadata was never native proof.
This exact class/field applicability gap remains #177/#180 work.

A separate unpublished compatibility candidate `01ed6d4e` tested legacy
`ak.wwise.ui.project.open` through the complete closed transaction on Console
2021.1 and 2022.1. Both native hosts returned exact `ak.wwise.unavailable` with
matching procedure URI and an instance-type refusal. Their original Gateway
states remain indeterminate; no verify or execute replay followed. Both whole
cases remain FAIL, and the candidate is not integrated or published as Console
support. These are host-specific observations, not removal of the Authoring API
from scope. Existing public Authoring-host restrictions remain intact.

Every native run preserved source full hashes, mtimes, tree metadata and tracked
source; owned processes ended and failed sandboxes remain quarantined. Further
work retains complete before/after file images for diagnosis and uses matching
SDK authority for plug-in named-list ordering. Original native failures are not
regraded by later code or offline comparisons. No ticket closes at this checkpoint.


## Twenty-fifth integration checkpoint

R25 code `883fd0c7` integrates actual-object conditions for existing Bus/AuxBus
references and scalars, existing-target create/merge binding, generic ancestor
rename preservation, and complete saved-model media observations. A move-to-single
media Preview now discloses source-proven optional empty saved None-state records;
verification reports exact new identities and preserves all remaining model data.
Bounded offline pages expose large eligible/actual details through the existing
transaction store. Neither old XML content nor distinct 2024 plug-in/Soundcaster
changes are normalized away. External-source verification's local Path shadowing
and source-status reads' missing local-host boundary are fixed.

The ordered Program roster contains 256 entries. Generated public scope remains
897 version rows, 228 unique URIs, 515 contracts and 32,978 branch records.
All 272,313 native obligations, owners and evidence requirements are retained;
116 exclusions and 272,197 unresolved rows remain. Default evidence mapping is
still outstanding implementation work, not a claim that those rows are proved.

Original runs stay separate: central `7228c25f` produced 820 passed / 5 failed
in 27.08s; test-only fixes selected the typed media readback instead of its list
position. The combined focus at `0311ab60` produced 208 passed / 1 failed in
117.62s, including those five repairs and all other original Program failures.
The final metadata-drift error-fixture repair at `883fd0c7` passed its sole
remaining node in 0.45s. All runs retained 1,875 unchanged tracked files and
zero owned processes. These are scoped successor passes, not a new full Program,
Non-live or aggregate 825-case pass. No Fresh was launched.

On exact earlier candidate `6ca8d96c`, the prospective sibling AuxBus reference
case passed once on each of the five native versions, with independent identity,
class, parent and reference checks. Source hashes/mtimes remained unchanged and
passing sandboxes were removed. That evidence does not cover R25's existing-source
scalar/create-merge changes. Its new three-effect collector has 18 pure controls;
matching native acceptance is pending. Original 2023/2024 media failures remain
retained, and the 2024 loss of non-default Soundcaster session values remains a
separate investigation. Old-version root Bus conditions and existing List
collision conditions remain same-parent implementation work. No ticket closes.

## Twenty-sixth integration checkpoint

R26 code `3c3423eb` binds older root Bus applicability to each version's actual
source predicates and resolves existing owned List members before evaluating
conditions. Merged members preserve their actual GUID, class, owner and opaque
path; compatible reference read projections retain all guarded fields. Old-root
and ordinary Bus witnesses have distinct receipts. The owned Mac Authoring
launcher now uses the actual bundled Wine path helper and distinguishes a
filesystem-only preflight failure from process cleanup.

The frozen candidate passed one central preflight (825 tests, 27.22s) and eight
cross-feature tests (7.89s), separately. Both retained all 1,876 tracked files
and zero owned processes. The Program roster contains 257 entries; public scope
remains 897 version rows / 228 URIs / 515 contracts / 32,978 branches. No new
full Program, Non-live, Fresh or native-Windows acceptance is claimed.

The first reviewed exact evidence requirement is now committed. One existing
2025.1 moveSingle program capture passed on this same candidate (1 test, 1.13s).
The existing full-product evaluator and identical reproducibility check both
returned expected exit 2: 116 approved exclusions, one implemented-but-unverified
row, and 272,196 unresolved rows. That exact row has program proof but no current
native attachment. Literal captured argv and all original obligations remain
intact. The default unbound inventory still reports 272,197 unresolved rows;
the explicitly selected capture overlay is the evidence-bearing result. Capture
and input hashes are retained in query-worktree ignored directory
`.waapi-skill-state/full-coverage/media-id-exact-r26-3c3423eb-r1/`.

Two isolated 2024 Authoring diagnostic attempts produced no business evidence.
Candidate `a79ef03b` failed before launch because the expected path helper was
absent. Fixed `f4abca75` launched the owned application but timed out waiting for
WAAPI after 60 seconds; cleanup completed and source hashes/mtime remained
unchanged. The Mac was independently reported locked, so visible startup-window
diagnosis awaits unlocking; lock state is not asserted as the timeout's cause.
Original roots remain frozen. Media/session preservation, native Bus/List
effects, unnamed RTPC graph construction and all other in-scope gaps remain
same-parent work. No ticket closes at this checkpoint.

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
