# Implementation checkpoint — resumed

Date: 2026-09-28. Parent issue #108; implementation tasks #109–#122, repairs #123/#124.
The user requested a quota pause on 2026-09-28 and explicitly resumed implementation
on 2026-10-01. The implementation Goal is active; approved real preflight, model
pilot, and acceptance may proceed after their prerequisite gates.

## Startup diagnosis after unlocking — 2026-10-01

- Unlocking restored desktop inspection, but did not resolve the background
  file-open stall. A bounded probe isolated the portable live-config read under
  `Documents`; a byte-identical managed-local copy resolved that first stall
  without changing the resolved SampleProject or sandbox paths or OS permissions.
- Frozen `9256ae8` Luna-high root `expansion-pilot-9256ae8-luna-high-r3`
  retains three FAILs. Every case stopped at the prompt-input audit before a
  Codex exec turn: no model-comparison or business acceptance credit is available.
  Each source full hash and project mtime remained unchanged; the failed copies
  remain quarantined and the one-shot launcher was unloaded.
- CLI-only native LaunchAgent probes held arguments, Skill bytes, disposable
  authentication state, and memory isolation constant. The nested empty-`.git`
  workspace timed out at 30.02 seconds; an independent directory completed in
  3.26 seconds. A new nested workspace with minimal valid Git metadata completed
  in 3.12 seconds, passed the unchanged prompt audit, and changed no workspace
  files. These are startup diagnostics, not Agent or Wwise PASS evidence.
- The existing harness now creates and strictly verifies that minimal valid
  repository, without a Git CLI dependency. The empty-marker regression failed
  before the repair on both platform contracts; the repaired workspace selection
  passed 18 tests and the full harness test file passed 381 / skipped 9 native
  Windows checks. Full Non-live at `d78be5b` completed with 11967 passed,
  one inventory-label failure, 118 skipped, and 27 deselected. Its documentation
  correction passed all nine focused documentation checks; harness and Skill
  bytes remain unchanged. This is not a single all-green full Non-live run.
  Fresh model pilots remain pending.
  The exact blocked Git/config filename remains
  unproven; the location-dependent stall and successful boundary replacement are
  established. New candidate gates and new pilot roots are required afterward.
  Original failed records must not be rewritten or verify-only replayed as PASS.
  Sanitized results and raw-record digests are in
  `../research/integration-expansion-startup-diagnostics-2026-10-01.json`.

## Resume update — 2026-10-01

### Completed entry-repair gates and next compact-directory candidate

- **Reviewed staged-notice grading repair — 2026-10-03:** #147 now resolves
  local owner and ancillary claims through shared typed roles, accepts an exact
  complete pre-Preview Effect plan followed by operation-specific post-Preview
  adoption, and validates a Stinger's stated old Trigger against both independent
  baseline and prepared pre-state. A private descriptor binds the planned effect
  to the immutable artifact; prose supplies no policy or native-class authority.
  Four distinct actual valid notice witnesses failed before repair. The
  independent corpus's first 19-pass/1-fail audit used a partially repaired
  snapshot, so it is not pre-repair RED evidence. Review then found separate
  intervening contradictions and stale post-Preview notice state: the new
  controls reproduced **9 failures / 6 passes**, then passed all **15** after
  correction. Explicit changed owners, values, refusal and policy conflicts
  invalidate the staged plan; neutral progress remains legal. Every Preview
  clears prior post-Preview notice state. The helper's repeated-Preview controls
  do not broaden formal admission: the archive still requires exactly one
  accepted Preview and matching transaction/hash receipts.
  Both independent review lanes are clear. All seven notice files passed
  **2229 tests** in **3.55 seconds**. Root's combined notice, harness, Broker,
  Skill-contract, documentation and interface-inventory gate passed
  **2828 / skipped 9 native-Windows checks**, exit zero in **22.81 seconds**.
  Log SHA-256: `a4e7634ff2dd5b72a0d3c3014dc21e7afe2b64268d65d58ae33ee8cc86a6fd03`;
  JUnit SHA-256: `4770d3799ae3e85b297dd3c14b8cc0e66da099ea721d729bc85986ce60ef5cf3`.
  Packaged Skill and Program inputs are unchanged from eba698d; its 6345/2
  Program result remains component evidence, not a new run. A complete new
  Non-live gate and then a new full thirteen-Agent-unit campaign plus boundary
  are next. Original automatic FAILs remain frozen, separately from the proven
  successful business outcomes; no historical replay or verdict promotion.


- **Five successful business effects; contextual notice grading remains — 2026-10-03:**
  candidate `eba698d9c9f461182b36c7c55ff9b8d2253d9d06` passed new Program
  **6345 / skipped 2** in **303.27 seconds**, then complete Non-live
  **14965 / skipped 119 / deselected 27** in **863.87 seconds**, both exit zero.
  Root `expansion-retry5-eba698d-sol-high-r1-cli1592` completed all five retry
  units plus the directly affected 2022 Stinger boundary. Independent business
  effects passed **5/5, with 28/28 assertions**. Automatic verdicts remain
  **1 Agent PASS / 4 notice-only FAIL / 1 separate boundary**; every other common
  gate passed. The sole automatic PASS is EXP25-C08. No historical promotion:
  - EXP22-C08 has a complete exact curve notice using the checked target's
    pronoun; actual curve and preservation checks pass.
  - EXP22-C09 discloses its exact named effect/notes before Preview, then confirms
    the matching Preview and authorized execution of that sole append before
    Execute. Repetition of all identifiers is unnecessary for this valid notice.
  - EXP25-C09 states the checked target, authorization and full impending effect
    across paragraphs; no substantive disclosure gap exists.
  - EXP25-M05 gives the sole owned Trigger change from Bonus to Backup_Team_Arrives
    and present authorized execution. The named-reference role repair is now
    proven by fresh binding, field discovery, Execute and independent outcome.
  EXP22-C08 consumes #154's corrected query-schema and performs successful
  separate exact-object reads. EXP25-C08 does not consume that schema and earns
  no additional Fresh disclosure credit. Honest Agent-owned baseline-proof
  limitations stay separate from the trusted oracle's preservation evidence.
  All 785 artifacts and metadata seals match; six source guards are unchanged,
  every oracle/reconciliation child closed, one PASS copy removed, four FAIL
  copies and one boundary copy quarantined, and scoped processes absent.
  Agent time is **631.94 seconds / 5 turns**, with **zero slow units** and one
  Preview/Execute/Verify per business unit. The launcher exited 1 and was unloaded.
  See `../research/integration-expansion-retry5-eba698d-sol-high-2026-10-03.json`.
  Preserve the mixed root without verify-only or regrading. Repair #147 using
  bounded stage-aware attested context and independent negative controls,
  then proceed directly to a new full thirteen-Agent-unit root plus boundary;
  do not repeat another costly failed-only loop for these valid notices.


- **Reviewed query-disclosure inventory refresh — 2026-10-03:** Program at
  `54930bd` completed with **6344 passed / 1 failed / 2 skipped**, exit 1 in
  **290.01 seconds**. The sole failure correctly detected an unsynchronized
  public-continuation seal after #154. Its log remains frozen (SHA-256
  `4e4c73d0cc66ab7dbb70ac4a5d524d4f8e0602d2b694e42e14cb420e720aaf22`).
  A precise before/after comparison proves only the five object.get rows'
  diagnostic-view disclosure changed; the other three source-contract digests,
  advanced query layer and all lane classifications are identical. Normal
  generation changed only the reviewed public-continuation digest and derived
  inventory digest in two JSON files. Markdown and counts remain unchanged:
  849 native lanes and 153 operation lanes, with no new coverage claim.
  Root reviewed that exact generated diff; the focused inventory gate passed
  **16 tests**, exit zero in **16.47 seconds**. Log SHA-256:
  `589577fa6e6a71631c05d7a6d7e95d3d59852edf75f672d4834255626af4cb59`.
  No Fresh run used 54930bd. Its prepared launcher remains unused. A new full
  Program gate and then Non-live are required on the refreshed candidate;
  future discovery-contract focused selections should include this inventory
  test before the broad gate.


- **Consolidated #147/#153/#154 repair candidate — 2026-10-03:**
  #147 recognizes bounded Preview-status and policy-record claims plus a
  curve-only scope noun; these cannot establish the primary effect or hide
  conflicting owners, policy modes, refusal or extra edits. Two actual witness
  regressions were RED before repair; the full notice gate passed **2164 tests**,
  retaining all prior 2131 controls.
  #153 attests the exact existing MusicStinger source only at the first binding
  of the named reference operation. Five pinned native-type indexes prove its
  class; creation kinds, later reference targets and genuine ambiguity remain
  unchanged. Its public binding RED5 became GREEN5; the combined binding/metadata
  gate passed **380 tests**. Two intermediate test failures incorrectly assumed
  older setLinked availability and were fixed to prove the existing boundary;
  a mistyped test path collected no tests and grants no evidence.
  #154 discloses the existing diagnostic view's one-object bound and five
  incompatible flags in query-schema/help, with a separate exact-object query
  for extra fields. Five missing-disclosure regressions were RED; the final
  affected query gate passed **49 tests** without changing parser/dispatch rules.
  A short operate clarification explains that returned policy_authorized is
  separate durable authorization, with no extra approval required. Review caught
  its initial CRLF size excess; the compact final reference is **19974 bytes**
  under canonical CRLF and retains the unchanged 20000-byte ceiling.
  Independent Standards and Spec reviews of each component are clear. Root
  combined validation passed **3564 / skipped 9**, exit zero in **28.38 seconds**.
  Log SHA-256: `c3b6e9698b7a66213e134fbe468f78cce99f73b44dc289f8c40bff60732cbc6d`;
  JUnit SHA-256: `88ce5203c07bccbec2a66c4b7fb9af8618b33d771043069754a43798a17cac0b`.
  New Program and Non-live gates are required because the packaged Skill changed.
  Then rerun the five failed units on a new candidate/root, followed by the full
  thirteen-Agent selection plus boundary once the affected units pass. Original
  534fdde results remain frozen; independent successful business effects are
  preserved separately from automatic failures.


- **Complete frozen pass and outcome-based attribution — 2026-10-03:**
  candidate `534fdde5eeac8466a766514e131f63c3d6656deb` passed Non-live
  **14845 / skipped 119 / deselected 27**, exit zero in **836.47 seconds**.
  Program inputs remain unchanged from 6b906cb; its 6258/2 result is component
  evidence only. Fresh root `expansion-acceptance-534fdde-sol-high-r1-cli1592`
  completed all thirteen Agent units plus the separate 2022 Stinger boundary,
  using Sol 6.1 high/default. Automatic results are **8 PASS / 5 FAIL**, with
  one boundary proven and no pending units or early stop. Independent outcomes
  prove **10/13 business effects**, not complete Agent acceptance:
  - EXP22-C08: all five business/preservation assertions pass; valid notice
    falsely rejected. A real supplementary query mixed view/include options,
    was rejected, and Agent honestly reported incomplete personal readback.
  - EXP25-C09: all six business assertions pass; complete prospective notice
    falsely rejected. Independent review accepts the workflow.
  - EXP22-C09: no execution; Agent misunderstood the available distinct durable
    policy authorization. This is not a missing authorization mechanism.
  - EXP25-C08: no execution; Agent claimed batched-read truncation. Captured
    Gateway JSON is complete, but presentation-budget telemetry is absent;
    actual presentation truncation versus mistaken inference remains unresolved.
  - EXP25-M05: no Preview/mutation after exact native MusicStinger binding was
    disclosed as ambiguous. Code diagnosis identified the named-reference
    existing-role attestation gap, tracked separately in #153. This is not the
    genuine 2022 capability boundary.
  All 1503 artifacts and metadata seals match; fourteen source hashes/mtimes are
  unchanged, eight PASS copies are removed, five FAIL copies and one boundary
  copy are quarantined, all oracles/reconciliation children closed, and scoped
  processes are absent. Agent execution totaled **1783.28 seconds / 17 turns**,
  with **zero slow units**. The one-shot launcher exited 1 and was unloaded.
  Preserve this mixed root without verify-only or regrading. The audited report
  is `../research/integration-expansion-full-534fdde-sol-high-2026-10-03.json`.
  Consolidate #147 notice-claim repairs and #153 typed existing-role disclosure;
  keep genuine Agent errors separate. Required final acceptance remains a new
  complete successful candidate/root plus identical verify-only.


- **Reviewed planned-effect reference repair — 2026-10-03:** #147 now links
  an attested definite primary owner, a named prospective Effect descriptor,
  a bounded saved-policy inspection and a later reference to that same effect.
  Display labels remain lexical context, never native class-ID authority;
  the immutable descriptor retains that authority. The existing Effect-kind
  predicate rejects a Sound/Source/ActorMixer substituted as a created effect.
  Wrong owners, competing descriptors, conflicting fields, extra changes and
  refusal remain rejected. Direct deictic refusal controls reproduced two
  failures before repair, then passed. Both Standards and Spec reviews are clear.
  The independent twenty-node corpus repeats one exact valid two-message witness
  against ten distinct substantive negatives; it is not ten positive paraphrases.
  Its initial 10/10 audit used incompatible test-helper phase commands and is
  preserved with an explicit seam erratum, not credited as predicate RED. Only
  private command projections were corrected after checking the raw Gateway
  phases; raw fixture/messages remain unchanged. Corrected 20/20 is post-repair
  evidence. The first author singleton had the same seam limitation and receives
  no predicate-RED credit. The real frozen notice rejection remains the original
  diagnostic evidence and is not regraded.
  Notice-focused validation passed **2131 tests**, retaining the prior 2091;
  root combined validation passed **2798 / skipped 9**, exit zero in **6.04 seconds**.
  Combined log SHA-256: `ddf551ab0ffa012afa98ca52180b0257146c7f7d2329ba149ffb47d2c5df9557`;
  JUnit SHA-256: `e86f75a05a6bf6ffe468a464f6948267922d709ddcb80463294a70a56d260b13`.
  No packaged Skill, public Gateway or #152 reconciliation behavior changed.
  Next: a new complete Non-live gate, then one fresh full thirteen-Agent-unit
  batch and the separate boundary. Do not spend another C09-only rerun or
  promote old automatic FAIL records.


- **Valid C09 workflow; notice-only grader false negative — 2026-10-03:**
  candidate `55df09712c37efa55026d3ae318f3b8983bae5ff` passed complete
  Non-live **14805 / skipped 119 / deselected 27**, exit zero in **848.28 seconds**.
  Program inputs stayed byte-identical to 6b906cb, whose completed gate remains
  component evidence only. Fresh root `expansion-c09-55df097-sol-high-r1-cli1592`
  preserved one automatic notice FAIL. Independent review accepts the actual
  workflow: all six outcome/preservation assertions, authorization, exact command
  provenance and the single Execute/Verify passed. The two pre-execution notices
  collectively identify the requested Sound and one named Wwise Gain append.
  Missing repeated identifiers are not missing business intent.
  Preview 8 -> unchanged same-transaction summary 9 -> exact Execute 10 -> Verify 11
  freshly exercises #152 with automatic Broker provenance passing. The snapshot
  preserves the artifact, event journal, summary, authorization and complete
  continuation; only matching current policy is added. This is scoped #152 proof,
  not an automatic Agent PASS or full-profile acceptance.
  The original FAIL root is frozen without replay/regrading: all **173 artifacts**,
  metadata seals and the source hash/mtime guard match; the sandbox is quarantined,
  cleanup completed and no scoped process remains. See
  `../research/integration-expansion-c09-55df097-sol-high-2026-10-03.json`.
  Repair #147's bounded entity references offline, preserving substantive negative
  controls. Do not repeat another C09-only loop: the next fresh candidate runs
  all thirteen Agent units plus the separate boundary, then identical verify-only
  if the complete root passes. No historical automatic verdict is rewritten.


- **Reviewed same-transaction snapshot and coordinated notice repair — 2026-10-03:**
  the user emphasized that the valid C09 workflow must not be mislabeled as a
  business failure. Its accepted independent evidence review and original
  automatic FAIL are recorded separately in the 6b906cb report.
  #152 now admits only an authenticated successful complete snapshot of the
  same pending policy-authorized transaction, with unchanged artifact, event
  journal, summary, original authorization and exact selected continuation.
  Only a matching `current_policy` projection may be added. The original
  pending Execute remains authoritative. Review caught list-only fixture bias;
  actual tuple-backed Broker records now pass, while malformed argv and JSON
  type-changing projections reject. Its focused gate passed **551 / skipped 9**.
  #147 decomposes coordinated baseline summaries, nominal Preview effects,
  recorded-policy claims and operation-matched execution summaries. Summaries
  never establish the primary effect. Wrong protected counts, foreign subjects,
  policy contradictions and refusal remain failures; present not-yet-executed
  status is accepted. The first independent 24-case audit remains sealed at
  **20 passed / 4 failed**; all four issues were repaired without changing the
  corpus. The notice-focused gate passed **2091 tests**, including all prior
  controls. Both review axes are clear after repair.
  The root combined gate passed **2758 / skipped 9**, exit zero in **5.93 seconds**.
  Log SHA-256: `5935ce40c735423ded24e05666b348828e15a3011cb27bda84cbca37658ba4f3`;
  JUnit SHA-256: `a8657ef711ac80efc3eae2ad6ea7957f360f3521bbf1a9f476514c39f873c710`.
  The packaged Skill and Program inputs remain unchanged from 6b906cb; retain
  that completed Program gate as component evidence, not a new run. A new full
  Non-live gate and fresh C09-only confirmation remain pending, followed by
  the full thirteen-Agent-unit selection and separate boundary on one candidate.


- **Two curve passes and one confirmed grading false negative — 2026-10-03:**
  candidate `6b906cb4436310c1902452ea92d676a5022deb9d` passed Program
  **6258 / skipped 2** in **318.00 seconds**, then complete Non-live
  **14557 / skipped 119 / deselected 27** in **880.21 seconds**, both exit zero.
  New root `expansion-focused3-6b906cb-sol-high-r1-cli1592` completed with
  **two automatic Agent PASS, one automatic FAIL and one separate boundary**.
  Both C08 versions passed. EXP22-C09's independent evidence review accepts the
  workflow: all six actual outcome/preservation assertions passed; same-tx
  snapshot 9 left Preview 8's artifact and authorization journal unchanged;
  Execute 10 exactly copied both selected continuations and executed once.
  Its notice clearly states the intended append. The automatic FAIL is a
  grader false negative, not an Agent or Wwise business failure. Preserve that
  original verdict while reporting this attribution explicitly.
  The mixed root is frozen without verify-only; 373 artifacts, all metadata
  seals and all four source guards match. PASS copies were removed; FAIL and
  boundary copies remain quarantined; no scoped process remained. See
  `../research/integration-expansion-focused-rerun-6b906cb-sol-high-2026-10-03.json`.
  #152 is extending only unchanged same-transaction snapshot admission while
  retaining the original exact Execute obligation. #147 is accounting for
  coordinated baseline summaries, nominal Preview effects and execution
  summaries without treating them as new edits. The next expensive rerun will
  focus on C09; shared notice paths retain offline witness/negative coverage,
  and final complete acceptance still runs all thirteen Agent units plus the
  separate boundary on one frozen candidate. No historical verdict is rewritten.


- **Reviewed claim and continuation repairs — 2026-10-03:** the user resumed
  work after the setting-change pause. Independent review reconciled the first
  withheld matrix's blank-paragraph expectation with the existing substantive
  adjacency contract: whitespace alone does not change the target. R1's corpus,
  29/11 result and artifact hashes remain untouched. R2 explicitly records this
  expectation erratum, retains the other nineteen pairs, accepts the original
  blank-line witness and rejects an interposed foreign subject. Current tests
  no longer append to the sealed first-audit artifacts.
  #147 fixes nine genuine positive rejections and historical creation being
  treated as a prospective effect. Typed spans prove current-state coordinates
  against the sealed baseline before excluding them from prospective values;
  owner inheritance, authorization and execution status have separate roles.
  Additional review found and repaired historical markers before the owner
  and a Preview-keyword exemption. The reported current-count concern was
  disproved at the public adapter; no unnecessary count refactor was made.
  All previous negative controls remain. Both review axes are clear after
  repair; #147's focused gate passed **1900 tests**.
  #152 retains the exact selected policy-Preview Execute across admitted,
  authenticated successful complete reads, while keeping Ask turn boundaries
  and default historical-profile behavior unchanged. Its review is clear.
  The combined notice, continuation, Broker and complete Skill-document
  regression passed **2510 tests / 9 native-Windows skips**, exit zero in
  **6.28 seconds**. Log SHA-256:
  `2dc3ede129e3b7fffe75be80a84aeced0ea96c993295e652f8aea2ec1ec664b6`;
  JUnit SHA-256:
  `11fd1557fe8c81ced50a360a1f16f62e1177657cc23b99175bf8ac3cef3c8809`.
  These are program/regression proofs, not new Agent acceptance. Freeze the
  combined candidate, complete its gates, then run a new three-case Fresh root
  plus the separate boundary. Only a successful root may receive identical
  verify-only, followed by the complete thirteen-Agent-unit acceptance batch.


- **Requested setting-change pause — 2026-10-03:** the user requested a pause
  after the current independent audit. #147's typed-role implementation passed
  its two-file focused gate **1811 tests** (all prior 1754 retained), with actual
  three-witness RED/GREEN and four extra-current-claim RED controls. Its first
  independently withheld audit then completed **29 passed / 11 failed**:
  nine expected-positive rejections and two expected-negative acceptances.
  The latter concern blank-paragraph owner inheritance and historical creation
  counted as a prospective edit. These are audit findings, not completed fixes;
  reconcile the paragraph-reset expectation with previously accepted whitespace
  inheritance before changing either implementation or a test expectation.
  The first matrix, expected/actual rows and JUnit are sealed under ignored
  `expansion-notice-role-context-withheld-r1/first-summary.json`.
  First log SHA-256:
  `b816af581cf2515408b725872a8d45d8db0d68ce1245957be60f8c4a56943385`;
  JUnit SHA-256:
  `ca3f24cb290cb3754eac2a0ed257cc3694676a42bddba58c4db6e5f8ed8005bc`.
  #152 remains reviewed with **494 passed / 9 skipped**; neither repair has
  been committed or run in a new Fresh campaign. All work is preserved in MAIN,
  with no active test or Wwise process. Resume from the withheld findings,
  preserve the first audit unchanged, then finish reviews and validation.


- **Latest frozen candidate and resumed repairs — 2026-10-03:** complete
  Non-live at `a1979dbc3fc4bfef443865e93be0c79633fa80a6` passed **14385 tests,
  skipped 119, deselected 27**, exit zero in **921.24 seconds**. The coordinator
  verified terminal process cleanup and clean tracked worktrees before launch.
  Log SHA-256: `3c500ffc71a0ee8855fee48e15b28364f374eedb152a979ac85f1a7e6eaf0779`;
  JUnit SHA-256: `527630e4402ce3e83bf6d5d750f839d47c0592a33c8527ad1d5a8899313b7abd`.
  Fresh root `expansion-focused3-a1979db-sol-high-r1-cli1592` completed with
  **zero Agent PASS, three FAIL and one separate boundary**. All sixteen
  independent business assertions passed across the three executed goals;
  this does not grant Agent acceptance. All three notices failed grammatical
  interpretation. EXP22-C08 additionally failed immediate continuation pairing:
  Preview 7 selected Execute, admitted baseline reads occupied records 8–26,
  and Execute 27 copied the selected command exactly. This is sequencing
  disagreement, not command reconstruction; #152 tracks the bounded repair.
  EXP25-C08 stopped correctly after a rejected ancillary query; its formal
  failure remains notice-only. The root is frozen without verify-only/regrading.
  All 631 artifacts and eight metadata seals match; all source guards are
  unchanged, retained projects remain quarantined and all scoped processes
  are cleaned. Detailed evidence is in
  `../research/integration-expansion-focused-rerun-a1979db-sol-high-2026-10-03.json`.
  #147 is moving from whole-sentence exceptions to bounded span-preserving
  owner, temporal, expected-effect and ancillary claim roles. Current-state
  coordinates must match sealed before-state and never satisfy prospective
  values; independent withheld positive/negative paragraphs will be checked
  after implementation is held. #152 retains a pending exact Preview command
  across admitted successful read-only baseline checks. Neither repair
  rewrites historical verdicts or relaxes mutation authorization. The user
  paused for a mode change and explicitly resumed; the Goal is active.
  #151 is now closed for its scoped instruction/readback inconsistency, based
  on reviewed wording, the completed Non-live gate, bounded readback use and
  correct stopping on the rejected ancillary query. This grants no Agent PASS.
  #152's pending-continuation implementation has reproduced the real sequence
  and an incomplete-read negative before repair. Its full harness/Broker
  focused gate passed **494 tests**, skipped nine native-Windows checks,
  exit zero in **2.63 seconds**. Standards and root Spec review are clear;
  the unchanged default profile remains strict, and expansion reads retain
  the selected exact Execute obligation. Log SHA-256:
  `65a72360bd8eea3112cd5b87bb9d9eec1aa569e3f24d3e45c9a84630dbe6e63c`;
  JUnit SHA-256:
  `c38260291664d02405e487c3cc8b6b73d5104a601c43f04c4b834cffdb10f90c`.
  New-candidate Fresh validation remains pending; #152 stays open.


- **Authorization grammar and requested readback repair — 2026-10-03:** the
  shared authorization classifier now retains original spans and owner evidence
  for active, passive and beneficiary clause roles. Ancillary authorization
  prose cannot grant authority or supply a missing expected effect. Independent
  paired controls cover policy, owner, uncertainty, refusal and extra actions
  across attenuation, effect and reference notices. Review found and repaired
  a contradictory coordinated policy suffix; only adjacent valid policy
  qualifiers extend the exempt span. All earlier negative controls remain.
  Actual frozen notices remain fixture witnesses, not historical regrading.
  Both Standards and Spec reviews are clear after repair. The combined
  configuration, notice, Broker and documentation gate passed **1907 tests**,
  exit zero in **4.26 seconds**. Log SHA-256:
  `5035a98b162a2f24de95da39c0e52b841ddff027dc69c55a3b9a1df3c2cba53a`;
  JUnit SHA-256:
  `a058f194bad9f6defeaadf5677c8e12b12c62b25dbe86f34fa2c84ffbbc54fcb`.
  Separate #151 clarifies the narrow requested-readback exception for
  `result_schema_checked`; transaction execution and stronger-proof claims stay
  closed. Complete Non-live at `ab2dbb9` then completed with **14383 passed,
  two failed, 119 skipped and 27 deselected**, exit one in **893.05 seconds**.
  Both failures concern #151's operate reference: an existing terminal-phrase
  assertion and the unchanged 20000-byte CRLF UTF-8 complete-read ceiling
  (the edited reference measured 20502 bytes). The first focused selection had
  missed these unit-level documentation contracts. This root is a FAIL; no
  Fresh campaign started. Preserve the ceiling and terminal semantics while
  compacting the reference, then run both affected unit files before a new gate.
  Failed gate log SHA-256:
  `46d373cbe2e1a39902154df867f0491563e9f9e6b75c61a45ccc05d6c2d919da`;
  JUnit SHA-256:
  `0d251340f81b4b941bf2f3418db0c4c65b8843ed7379a57b4bf6262d3dac23a0`.
  The doc-only follow-up restores the established terminal wording and removes
  duplicated control-plane prose without changing routes, metadata boundaries,
  output integrity or failure stops. The reference is **19826 CRLF UTF-8 bytes**;
  the 20000-byte ceiling and tests are unchanged. Both complete affected unit
  files plus the Broker file passed **132 tests**, exit zero in **1.91 seconds**.
  Log SHA-256: `50c9b4ab9461ee12524525079f6cb152261e013f27f491424b80990d0dc49d46`;
  JUnit SHA-256: `3cceda8744e32df4ac56ce0d19edd48e1bc242cadde8dedad556cc2a0685b5f1`.
  Complete Non-live at `7f512f1` then preserved another FAIL: **14382 passed,
  three failed, 119 skipped, 27 deselected**, exit one in **894.71 seconds**.
  The additional failures were stale exact prose assertions in
  `test_skill_contract.py` and `test_skill_gateway_contract.py`, omitted from
  the previous focused selection. Log SHA-256:
  `c8b6ec862678108bcdc3594e07a973a4348636437fefd777a4d857048fae3a9d`;
  JUnit SHA-256:
  `f6553aff959324ee179e125e05c3d0ace517d2eb587a3e3183dc23fa90ab31f7`.
  The follow-up explicitly retains binding-owned metadata scope and updates
  prose assertions to the independently reviewed equivalent shared-step wording,
  including numbered binding-before-discovery checks and verbatim machine output.
  Both review axes found no weakened obligation. All `test_skill*.py` unit
  files, the semantic builder audit, documentation inventory and Broker file
  passed **174 tests**, exit zero in **1.84 seconds**. The reference measures
  **19877 CRLF UTF-8 bytes**; its ceiling remains unchanged.
  Focused log SHA-256:
  `515ae2c2058aff283c11e00b063f3fc7be09baa137317dbcbb55e834b52ded85`;
  JUnit SHA-256:
  `5b83a7f72cc991d1605a556ce2af390ab295619a03932a3fe7092f3cb41c264b`.
  No Fresh run used either failed gate candidate. New complete validation and
  affected Fresh acceptance remain required.


- **Sol-high focused follow-up — 2026-10-02:** candidate `7652745` passed
  offline model/profile validation before a new one-shot launcher. Root
  `expansion-focused3-7652745-sol-high-r1-cli1592` completed **zero Agent PASS,
  three FAIL, one separately proven boundary**, with no pending or early stop.
  Both C08 units executed once and passed all five independent outcome checks,
  but failed the notice gate: subject-first authorization clauses were mistaken
  for additional physical edits. Independent diagnosis identified a grammatical
  role defect; original FAILs remain frozen without verify-only or regrading.
  C09 stopped safely before Preview after claiming incomplete catalog output.
  Captured output is complete, but original output budget and model-facing
  truncation metadata are unavailable, so false truncation is not proved.
  C08/2025 also made 19 scoped read-only calls after terminal Verify, consuming
  the #149 getter disclosure. This proves that component's use, not business
  acceptance: the Broker admits these reads while the Skill's no-extra-proof
  rule prohibits them. That policy mismatch needs explicit reconciliation.
  The run took **476.57 Agent seconds** across three turns; none exceeded the
  seven-minute slow threshold. All 582 archived artifacts and eight metadata
  seals match, all four source guards are unchanged, failed copies are retained,
  reconciliation children were reaped, and the launcher ran once, exited 1 and
  was unloaded with no scoped processes. Detailed evidence and exact digests
  are in `../research/integration-expansion-focused-rerun-7652745-sol-high-2026-10-02.json`.
  A shared active/passive authorization-clause repair and independent paired
  offline controls are being prepared before any further Fresh attempt.
  Separate repair #151 reconciles explicitly requested actual-state readback
  after `result_schema_checked` with the existing bounded public read lane.
  The transaction remains closed; current values do not prove preservation
  without a baseline. Its nine new authenticated Broker regressions cover
  permitted scoped reads and rejection of writes, reverification and public
  scope escapes. The focused Broker file passed **58 tests**, exit zero;
  independent Standards/instruction-consistency review found no findings.
  The Broker still permits bounded exact-ID reads within its owned project;
  these tests do not claim a runtime requested-target allowlist.

- **Explicit Sol-high configuration registration — 2026-10-02:** `a41d337`
  passed complete Non-live **13990 / skipped 119 / deselected 27**, exit zero
  in **870.64 seconds**. The attempted Sol-high focused launcher exited 2 at
  argument validation: the reviewed expansion configuration set still contained
  Luna high/medium and Sol medium only. No campaign root was created, no Agent
  or Wwise execution receives credit, and the one-shot launcher was unloaded.
  Its stdout/stderr and preflight-rejection record remain preserved. This was
  a missed coordinator preflight check, not a business or model failure.
  The development expansion profile now explicitly adds only
  `(gpt-6.1-sol, high, default)` to the matching code/data allowlists, following
  the already documented reasoning-depth follow-up. Defaults, cases, policies,
  budgets, service tier and retry constraints remain unchanged. Historical
  profile snapshots/roots are not edited; the changed definition digest
  requires a new candidate and root. Tests first reproduced the three model,
  matrix and campaign validation rejections, then passed the newly reviewed
  configuration on both entrypoints while still rejecting unreviewed effort
  and priority-tier combinations. The persisted configuration/CLI/notice/docs
  gate passed **1472 tests**, exit zero in **2.25 seconds**. Log SHA-256 is
  `c461a672a8ba3705da66c757efb47acf38137199681045c0b4e0fdf99d013f0b`;
  JUnit SHA-256 is
  `6eeb6fc99d2d6aa331cc47b88da25dcdf4f583701d5d4c55f2cb57b2b232e262`.
  The completed `a41d337` full Non-live is unchanged-component evidence, not
  a new full-suite run for this configuration-only successor. No notice,
  verifier, runtime or public Gateway behavior changed in this registration.
  Independent Standards and Spec reviews found no findings. A new Sol-high
  focused root remains required; final acceptance remains pending.

- **Repeated Medium policy interruption and composition gap — 2026-10-02:**
  frozen `d6430a0` passed complete Non-live **13863 / skipped 119 / deselected 27**,
  exit zero in **843.76 seconds**. New root
  `expansion-failed3-d6430a0-sol-medium-r1-cli1592` completed all four units:
  **one Agent PASS / two FAIL / one boundary**, no pending or early stop.
  EXP25-C08 passed. EXP22-C08 again completed its effect with all five
  independent assertions true, but its valid combination of exact target,
  attested Attenuation qualifier and policy-authorization summary failed the
  notice grammar. EXP22-C09 again requested human confirmation despite a
  `policy_authorized` Preview with `explicit_confirmation=false` and next
  command `execute`. Its safe stop remains genuine Agent incompletion, with
  no goal execution or formal after-state.
  The mixed root is frozen without verify-only/regrading. Its launcher ran
  once, exited 1, was unloaded and left no scoped process. All four source
  guards match; the passing sandbox was removed, two failures and the boundary
  remain quarantined, and both failure reconciliations were reaped. The three
  retained process records show cleaned/exited/no residuals. Deleted PASS
  process details are not separately sealed; only its sealed lifecycle,
  directory removal and terminal empty scope are claimed. Audit validated
  **455 artifacts / 18901730 bytes / eight metadata seals**. Agent time was
  **346.55 seconds**, three turns, zero slow, two Execute/Verify pairs. Exact
  digests, usage and limits are in
  `../research/integration-expansion-failed-rerun-d6430a0-sol-2026-10-02.json`.
  After compositional notice validation, the next new focused root will use
  **GPT-6.1 Sol high / default** for the two failed units, with EXP25-C08 as a
  directly related regression control and the separate EXP22-M05 boundary.
  Medium twice made the same explicit-policy-flow error; this justifies the
  targeted reasoning-depth follow-up, not a general model ranking or rewriting
  Medium FAILs. Final complete acceptance must use the successful focused
  candidate and identical model/settings. Previously prepared Medium full
  launchers remain unused and preserved. No public authorization relaxation,
  prompt workaround or automatic approval is introduced.
  The #147 successor composes an exact identity atom, optional qualifier of
  its independently attested live role, and a coordinated authorization
  summary from shared closed provider/grant/referent/change-noun components.
  Optional grammatical particles do not discard preceding owner spans. The
  real failing 2022 notice and passing 2025 notice remain immutable fixtures;
  45 component combinations and 45 paired foreign-identity negatives exercise
  their composition. Additional wrong-role, provider, policy, polarity,
  adjacency, value and extra-edit controls pass. Review exposed a curve-range
  noun exemption leaking into plugin/reference contexts; typed curve-range
  handling now rejects those contexts before generic fallbacks, and the curve
  lane still validates the complete owner prefix. Final Spec and Standards
  rechecks are clear. **1377 affected-file tests** pass; the coordinator's
  persisted notice/documentation gate passed **1386 tests**, exit zero in
  **2.20 seconds**. Log SHA-256 is
  `2e0b3a50af30dcedfd672c7d7c2a0b17ed745257d0bc8605c237cc730c688d7e`;
  JUnit SHA-256 is
  `2595e7489cd17b56b3cc51ea4685688aed0a26d806e9d132de1fe7a1fffb2314`.
  Packaged Skill and fixed Program inputs remain unchanged. Complete successor
  Non-live and new Sol-high focused/Fresh evidence remain pending; no frozen
  result was replayed or regraded.

- **Sol-medium focused follow-up — 2026-10-02:** frozen `5278a15` passed
  complete Non-live **13807 / skipped 119 / deselected 27**, exit zero in
  **859.44 seconds**. Root
  `expansion-failed3-5278a15-sol-medium-r1-cli1592` completed all four units:
  **zero Agent PASS / three FAIL / one boundary**, no pending or early stop.
  Both C08 units correctly used the disclosed `attenuation_handle` field and
  completed the intended effects, with all five independent assertions passing
  on each version. Their notices still failed: C08/2022 retained a policy
  qualifier as an alleged object-owner prefix; C08/2025 rejected an exact
  identity-only target statement and the adjacent owner-omitted curve edit.
  These are separate notice-interpretation gaps, not another declaration error.
  EXP22-C09 reached a Preview whose authorization was `policy_authorization`,
  `explicit_confirmation=false`, state `policy_authorized` and next command
  `execute`, but the Agent requested human confirmation and stopped. There was
  no goal execution or formal after-state; this is genuine safe Agent
  incompletion, not a reason to weaken the authorization contract.
  The root remains frozen without verify-only/regrading. The launcher ran once,
  exited 1, was unloaded and left no scoped process. All four source guards
  match, all retained process scopes were cleaned and all three reconciliations
  reaped. Audit validated **578 artifacts / 24460497 bytes / eight seals**.
  Agent time was **324.92 seconds**, three turns, zero slow cases and two
  Execute/Verify pairs. Exact gate digests, usage and evidence limitations are
  in `../research/integration-expansion-failed-rerun-5278a15-sol-2026-10-02.json`.
  This follow-up does not establish a general model ranking: Sol completed the
  previously incorrect declarations but made a different policy-flow error.
  Keep Sol medium for the next bounded failed-only validation. Consolidate the
  confirmed provider-qualifier and adjacent exact-target notice gaps first;
  final complete same-candidate acceptance remains pending.
  The #147 successor consumes only closed policy-provider qualifiers inside
  complete authorization nouns, preserving prior owner spans and rejecting
  unknown providers/policies. Exact positive ID/name/path target statements
  are distinct from curve-subject declarations. Both owner-omitted and `其`
  edits may inherit only within the first substantive clause of the immediately
  following sentence; comma-separated intervening subjects cannot borrow the
  earlier identity. Source, ordered points, shape, polarity, remaining edits
  and Preview/Execute timing retain their independent checks. Honest
  result-schema-only verification wording remains permitted without granting
  readback credit. Actual two-notice RED/GREEN, provider/target contrasts and
  the main-review same-sentence antecedent regressions all pass. Final Spec
  and Standards rechecks are clear; **1250 affected-file tests** pass.
  The coordinator's persisted notice/documentation gate passed **1259 tests**,
  exit zero in **1.82 seconds**. Log SHA-256 is
  `1eb401f1c2989c41a13ce626e9fe1e41288a01aefb2ec4383511cbc77d420515`;
  JUnit SHA-256 is
  `cba7eff62a0a1426c6b3e38c1711ab057e47e4dcf5e932712d76852b301285af`.
  No packaged Skill, public authorization rule, prompt or fixed Program input
  changed. Complete successor Non-live and fresh failed-only validation remain
  prerequisites for final acceptance; the Agent's C09 confirmation mistake
  receives no API workaround or historical PASS promotion.

- **Repeated Agent error and remaining notice-language gaps — 2026-10-02:**
  `1faaa5d` completed Non-live with **13566 passed / 119 skipped / 27 deselected**,
  exit zero in **862.89 seconds**. Its packaged Skill and Program inputs remain
  unchanged from the passing `492c30a` component. New root
  `expansion-failed3-1faaa5d-luna-high-r1-cli1592` finished all four units:
  **zero Agent PASS / three FAIL / one boundary**, no pending or early stop.
  EXP22-C08 again used `attenuation` where both schema and continuation
  explicitly required `attenuation_handle`, and stopped before Preview.
  EXP22-C09 and EXP25-C08 again completed the business effects with all six/five
  independent assertions passing, but retained notice-only FAILs. Their new
  wording exposes shared language gaps: the sealed Sound role's Chinese
  pronoun, a planned-change noun in execution/authorization sentences, and
  prospective intent expressed by the actual edit clause. This warrants a
  consolidated offline language check before further Fresh expense; accepting
  a wrong declaration-field alias is not a repair.
  The root is frozen without verify-only/regrading, launcher unloaded, all
  four source guards unchanged and all retained processes cleaned. Audit
  validated **576 artifacts / 23520085 bytes / eight metadata seals** and
  reaped all three reconciliation scopes. Agent time was **523.59 seconds**,
  three turns, zero slow cases, two Execute/Verify pairs. Exact hashes, usage
  and evidence limits are in
  `../research/integration-expansion-failed-rerun-1faaa5d-2026-10-02.json`.
  Repairs #148/#149/#150 are closed for their independently reviewed,
  program-proven scoped changes; none claims full business acceptance or
  Fresh getter consumption. #147 and #122 remain open. After consolidated
  notice verification, the next fresh failed-three selection will use
  **GPT-6.1 Sol medium / default** to combine repair validation with the
  targeted C08 model follow-up. Luna twice ignored an explicitly disclosed
  declaration field; the earlier Sol-medium pilot passed its three different
  units. These observations justify a bounded follow-up, not a general model
  ranking or Luna PASS. The next complete acceptance must use the same frozen
  candidate and Sol settings as its successful failed-only root; no model
  change inside an existing root is permitted. Previously prepared Luna
  launchers remain unused and preserved.
  The #147 successor shares closed role-language, planned-change noun and
  execution-polarity rules. Operation validators retain exact independent
  identities, immutable Preview agreement, values, curve order/shape/units,
  remaining owner/action spans and timing. Prospective curve frames retain
  source spans rather than reconstructing paragraphs. The separate reviewer
  authored 24 positive/negative pairs from closed business facts before
  executing the new implementation; the reviewer had legacy-code context,
  so this is not a blind benchmark or Agent evidence. Initial execution
  rejected 22/24 valid positives while rejecting all 24 negatives. All 48 now
  pass, together with 120 cross-product preservation/contradiction checks and
  every prior notice control. Reviews additionally exposed explicit-kind,
  cross-role qualifier, negated antecedent and primary-refusal exemptions;
  RED/GREEN regressions resolve each. Final Spec and Standards reviews are
  clear. Effect-native-kind claims are checked separately from Wwise-prefixed
  plugin display labels; no display-name-to-class-ID proof is invented.
  The final affected-file gate passed **1194 tests**; the coordinator's
  persisted notice/documentation gate passed **1203 tests**, exit zero in
  **1.62 seconds**. Log SHA-256 is
  `d25b398efec64672cc655c0e584dafa6a577bb695129f9248bd5e705153b4317`;
  JUnit SHA-256 is
  `c35921cadf72ba6fb5b2b2d40fcd662f975376ed9d85aaf21fed46d75564d13a`.
  Packaged Skill and fixed Program inputs remain unchanged from `492c30a`.
  Successor complete Non-live and fresh acceptance are pending. Neither
  historical FAIL root was replayed or promoted.

- **Complete three-failure rerun — 2026-10-02:** frozen `492c30a` passed
  five-version Program **6258 / skipped 2** and complete Non-live
  **13503 / skipped 119 / deselected 27**, both exit zero. The subsequent
  `expansion-failed3-492c30a-luna-high-r1-cli1592` root completed all four
  selected units: **zero Agent PASS / three FAIL / one separate boundary**,
  zero pending and no early stop. EXP22-C08 received the correct declaration
  field `attenuation_handle` in both schema and continuation, but submitted
  `attenuation`; Gateway rejected it before Preview or mutation. This is a
  genuine Agent input error, not missing disclosure or the earlier typed-role
  ambiguity. EXP22-C09 and EXP25-C08 completed their intended business effects
  with six/five independent assertions passing, but failed the visible notice
  gate. C08's Gateway result-schema-only verification remains distinct from
  the independent project's stronger outcome evidence. Neither C08 consumed
  the getter schema, so no Fresh #149 getter credit is assigned.
  The original FAIL root stays frozen without verify-only or regrading.
  Its one-shot launcher exited 1, was unloaded, and left no scoped process.
  All four source hash/mtime guards match; three failures and the boundary
  remain quarantined. Audit validated **576 artifacts / 23514269 bytes / eight
  metadata seals**; all retained process records show successful cleanup and
  all three failure reconciliations were reaped. Agent time totaled
  **471.49 seconds**, three turns, zero slow cases and two Execute/Verify pairs.
  Exact gate hashes, usage and limitations are in
  `../research/integration-expansion-failed-rerun-492c30a-2026-10-02.json`.
  Root coordination now uses the user's Astra-high selection; the formal
  tested model remains Luna high. Diagnose and consolidate the notice
  false negatives before a fresh failed-only root; do not relax the public
  declaration contract to conceal an Agent error. Final full acceptance
  remains pending.
  The #147 successor normalizes a complete attested identity only into its
  immediately adjacent, operation-owned Preview effect. Ordered points supply
  their own count; current/history-only descriptions and execution refusals
  cannot establish prospective intent. Full original identity and remaining
  clauses retain contradiction checks. Actual two-notice RED/GREEN and 63 new
  contrast checks leave all 890 earlier notice checks passing (953 total).
  Initial Spec and Standards reviews found two P2s: inheritance could reach a
  later Preview and an explicit execution refusal could be ignored. Both were
  repaired with RED/GREEN regressions; both final review axes are clear.
  The coordinator's persisted notice/documentation check passed **962 tests**,
  exit zero in **1.16 seconds**. Log SHA-256 is
  `08262847706c5975e7189479cb1091efce5f0f9cfafedd7431ce4193308b938e`;
  JUnit SHA-256 is
  `d35478fe6a16cc53c7feb0237cec1cd631f8a4961b344e9fedff3f31f5216b56`.
  This is harness-only work; packaged Skill and fixed Program inputs are
  unchanged from `492c30a`. Complete successor Non-live and Fresh validation
  are still required. The concrete historical notices are regression fixtures,
  not a regrading or promotion of either frozen Agent FAIL.

- **Complete failed-five batch and typed-role repair — 2026-10-02:** frozen
  `db82de6` passed complete Non-live **13349 / skipped 119 / deselected 27**,
  exit zero in **833.94 seconds**. Log SHA-256 is
  `73dfddcc86fb4279f9bd160c1544184f3ffba01beaaa8ed1cefe515b6f19f959`;
  JUnit SHA-256 is
  `271810c84395827a83941f1c1ce33294cf706d14eee02a013c24c77bb496d008`.
  Packaged Skill and Program inputs remain the passing `fa51197` component.
  Root `expansion-failed5-db82de6-luna-high-r1-cli1592` completed all six
  selected units: **two Agent PASS / three FAIL / one separate boundary**,
  zero pending and no early stop. EXP25-C09/M05 passed. EXP22-C08/C09 completed
  the business effects with all five/six independent assertions passing, but
  their prospective result and provider-authorization notices failed grading.
  EXP25-C08 stopped safely after correct Attenuation binding returned an
  ambiguous business-kind comparison with no candidates. It did not Preview,
  execute or produce after-state assertions. Neither C08 consumed the #149
  getter schema; no Fresh getter credit is assigned.
  #150 now resolves only the pinned attenuation role from its exact live
  `Attenuation` class, checks identity/role/version before handle storage, and
  marks comparison provenance `closed_role_live_type`. `semantic_kind` and
  global creation kinds remain unchanged. Focused Core Gateway/adapter tests
  passed **244 tests**. The #147 follow-up accepts complete prospective,
  owned Preview descriptions with temporal intent without requiring an
  imperative verb; current/history-only, refusal, contradictory and extra
  changes remain negative. Coordinated notes retain full owner-prefix proof
  before qualifier trimming and may target only the planned new Effect.
  **890 focused notice tests** pass; final independent Spec and Standards
  reviews for both repairs are clear. Combined root regression passed
  **1884 tests**, exit zero in **33.82 seconds**. Log SHA-256 is
  `917f15724f6d18e26d7b3c7f6c8c4bc8476f80408572ef59d662f1d58627f50d`;
  JUnit SHA-256 is
  `171fedf27377200d5f30bdb885e7f18580014b84fccdfbfc5c0e91d09e3a4a93`.
  No owned test process or diff-check error remained.
  The original FAIL root stays frozen without campaign verify-only or regrading.
  Its launcher ran once, exited 1, was unloaded and left no scoped process.
  All six source hash/mtime guards match. Two passing copies were removed;
  three failures and the boundary stay quarantined. Three failure reconciliation
  scopes were reaped; retained metadata record exited processes and no residuals.
  Deleted PASS process-cleanup details are not separately in the attempt
  manifest; sealed PASS lifecycle/deletion and terminal empty scope are verified.
  Evidence/report audits validated **685 artifacts / 25838575 bytes / eight
  metadata seals**. Exact results, usage and limitations are in
  `../research/integration-expansion-failed-rerun-db82de6-2026-10-02.json`.
  New fixed Program and complete Non-live gates are required for the #150
  packaged Gateway/contract change, followed by exact three-failed-Agent-unit
  plus boundary validation, identical verify-only, and final full acceptance.

- **Complete exact-unit rerun and grammatical-role repair — 2026-10-02:**
  frozen `fa51197` passed five-version Program **6176 / skipped 2**, exit zero
  in **294.77 seconds** (log SHA-256
  `1a42f8d5cc3876ea4c7440dc939fbfdf4c5b7ff2bbdb7be5dd3f77f41e4061d4`),
  and complete Non-live **13207 / skipped 119 / deselected 27**, exit zero in
  **852.65 seconds**. Non-live log SHA-256 is
  `45bb27057343b2e8493fcd224be4e70c557f76fd3813444020deda38091bf23d`;
  JUnit SHA-256 is
  `aa89faf8dfbdfb3eb5e2400df8f783a93d0ae0cf080946fc868e14012407e618`.
  Exact-unit root `expansion-failed6-fa51197-luna-high-r1-cli1592` completed
  all seven selected units: **one Agent PASS / five notice FAILs / one separate
  boundary**, zero pending and no early stop. All six Agent workflows executed
  and verified once, with every independent business assertion passing.
  Both C08 units retain the weaker Gateway `result_schema_checked` state.
  Neither C08 Agent called the attenuation getter or discovered its schema;
  this root grants no Fresh #149 getter-consumption or functional coverage.
  Disclosure-to-parser and fake-dispatch proof remains five-version Program
  evidence. EXP25-C06 passed; five other notices failed grammatical parsing.
  The #147 follow-up now binds target-bearing introductions, adjacent-clause
  owner/field continuity and semantic creation verbs, while distinguishing
  operation, authorization and execution nouns. All owner-bearing positive
  noun exemptions validate their explicit owner before exemption; unsupported
  target-subject declarations fail rather than disappearing. A separately
  valid primary effect is still required. Contradictory quoted notes, wrong or
  ambiguous owners, extra changes, values/units/shapes and timing remain negative
  controls. All five actual witnesses and **818 focused notice tests** pass;
  final independent Spec and Standards rechecks are clear. Root combined
  regression passed **1568 tests**, exit zero in **24.30 seconds**. Log SHA-256
  is `13b6b01a08f711d567361362c354b7f63088b3a8fba93bf838221c10aac9b603`;
  JUnit SHA-256 is
  `ae0f36e6e8ceac32e87360d8614ecd693832591381143e126882738bbe9d570b`.
  No owned test process or diff-check error remained. Packaged Skill and
  Program inputs are unchanged by this notice-only repair.
  The original FAIL root remains frozen without campaign verify-only or
  regrading. Its launcher ran once, exited 1, was unloaded, and left no scoped
  process. All seven source hashes and project mtimes remained unchanged;
  trusted actors closed and reconciliation children were reaped. The one PASS
  copy was removed; five failed copies and the boundary remain quarantined.
  Evidence and report reviews validated **975 artifacts / 38928303 bytes /
  eight metadata seals**. Exact results and usage are in
  `../research/integration-expansion-failed-rerun-fa51197-2026-10-02.json`.
  New complete Non-live, exact failed-five-Agent-unit plus boundary validation,
  identical verify-only, and final full thirteen-Agent-unit plus boundary
  acceptance remain required. Unused full launchers remain unused.

- **Complete failed-only batch and consolidated repairs — 2026-10-02:**
  frozen `86b475e` passed complete Non-live **13042 / skipped 119 /
  deselected 27**, exit zero in **817.38 seconds**. Log SHA-256 is
  `dd2a401037f266523bb5501e03b1a52a169a3dd812313395da99a859b5754a8d`;
  JUnit SHA-256 is
  `94e20a1c3d6018e5cf772ba240ca1f18f54f6c3d2ec76b86d4c6947b5369c4a4`.
  Root `expansion-failed7-86b475e-luna-high-r1-cli1592` completed all eight
  selected units: **one Agent PASS / six FAIL / one separate boundary**,
  zero pending and no early stop. EXP22-C06 passed; five other units completed
  their business effect with all independent assertions passing, but failed
  notice interpretation. EXP25-C08 retains the weaker Gateway
  `result_schema_checked` boundary. EXP22-C08 safely stopped before Preview
  after bare `metadata attenuation` received exit 2. Its fixed-route schema
  omitted mandatory selector and curve-role guidance; #149 repairs that
  disclosure without changing parser or dispatch behavior. Five-version tests
  consume the actual schema and check exact dispatch and `agent_result`;
  focused metadata/typed-request validation passed **226 tests**.
  The consolidated #147 notice repair resolves attested target references and
  placement, distinguishes request/authorization nouns from edits, and checks
  coherent historical, delta and complete prospective curve statements. It
  requires affirmative exact midpoint intent and the three-point single-middle-Y
  guard before indexing; foreign owners, contradictions, malformed values and
  extra changes remain negative controls. All five actual witnesses and
  **676 focused notice tests** pass. Final independent Spec and Standards
  reviews for both repairs are clear. Root combined regression passed
  **1426 tests**, exit zero in **25.51 seconds**. Log SHA-256 is
  `cf94c69a824bc519aed2c784c6e303746f6598692c1d05d5ffd2a7a32a71432b`;
  JUnit SHA-256 is
  `24fa7a8562e27ec2718882b60cd8192e49373bbfe511dbe54e2db79355155432`.
  The frozen FAIL root is unchanged, without campaign verify-only or regrading.
  Its launcher exited 1, was unloaded, and left no scoped process. All eight
  source full hashes and project mtimes remained unchanged; actors closed and
  children were reaped. The sole PASS copy was removed; six failed copies and
  the boundary remain quarantined. Evidence/report reviews validated
  **1188 artifacts / 44947559 bytes / eight metadata seals**. Exact units,
  attribution, gates and usage are in
  `../research/integration-expansion-failed-rerun-86b475e-2026-10-02.json`.
  New fixed Program and complete Non-live gates are required because #149
  changes the packaged Gateway. Existing exact-unit filters can select only
  the six failed Agent units plus the separate boundary, avoiding a repeated
  EXP22-C06 control. Fresh failed-only, identical verify-only and final full
  thirteen-Agent-unit plus boundary acceptance remain outstanding.

- **Frozen partial root and follow-up repairs — 2026-10-02:** candidate
  `719e3e0` passed complete Non-live **12962 / skipped 119 / deselected 27**,
  exit zero in **860.71 seconds**. Log SHA-256 is
  `c165a27b9598b6a77260f5c51e2d4cc68efdc3078c28aed272a86348cbd89256`;
  JUnit SHA-256 is
  `84d72f3a640213c0742b4b1a22ace58f754cf65125d6ee233b2dc704523abc14`.
  Fresh root `expansion-failed7-719e3e0-luna-high-r1-cli1592` stopped after
  three of eight units: **zero Agent PASS / one canonical FAIL / one BLOCKED /
  one separate boundary / five pending**. Matrix records two Agent FAILs.
  C06 executed and verified once with all seven independent business assertions
  passing, but its midpoint-only post-Preview notice remained a grading FAIL.
  C08 contains a genuine split-handle declaration error, authenticated and
  rejected before dispatch with exit 126 and null runner/payload. No Preview,
  authorization or execution occurred. The archive's read-only-query rejection
  branch could not represent that declaration rejection, causing BLOCKED.
  #148 adds a narrow terminal negative-evidence lane requiring exact parser,
  authority/revision, unchanged bound composition and reconciliation proof;
  malformed declarations remain prohibited and the Agent result remains FAIL.
  Its focused archive/CLI/Broker regression passed **259 tests**; independent
  Spec and Standards review is clear. The #147 follow-up instead permits the
  attested exact earlier plan to supply unchanged endpoints/shape only when a
  distinct post-Preview notice identifies the old/new midpoint, references the
  Preview, preserves identity/notes and excludes the attested sibling. Its
  author-focused regression passed **593 tests**, retaining all prior controls
  and rejecting the additional creation/removal/clear actions found in review.
  Final independent Spec and Standards rechecks are clear. The root's combined
  archive, notice, policy, Broker, CLI, task, matrix and campaign regression
  passed **1117 tests**, exit zero in **19.39 seconds**. Log SHA-256 is
  `2fa6e0b9cce496913e72becf111148b38e1a12bc78d1e221076c1d7b7b391ccb`;
  JUnit SHA-256 is
  `ee219bf835a265a5de4e13ec18c2b65cbdea393eebe7065b4494cc1ce79d101b`.
  No owned test process or diff-check error remained.
  The original partial root stays frozen without verify-only or regrading.
  Its one-shot launcher exited 3, was unloaded and left no scoped process.
  All three source hashes/mtimes remained unchanged; actors closed, children
  were reaped and all three projects remain quarantined. Independent evidence
  and report reviews validated **477 artifacts / 15473104 bytes / eight seals**.
  Exact partial results, gates and usage are in
  `../research/integration-expansion-partial-719e3e0-2026-10-02.json`.
  A new gated candidate, failed-only batch and final full acceptance remain
  required; unused full launchers remain unused.

- **Reviewed notice repair #147 — 2026-10-02:** all six sealed contextual
  notices now pass without changing Skill behavior, business oracles, prompts,
  authorization, or historical outcomes. Notice grading resolves references
  only against the uniquely attested target and distinguishes sealed old
  midpoint claims from the requested new scalar or complete tuple. Compatible
  units, finite values, complete syntax and boundaries remain mandatory;
  wrong owners, extra changes, malformed origins and contradictory values
  remain negative controls. Both independent Spec and Standards reviews are
  clear. Author-focused validation passed **540 tests**, preserving all prior
  controls; the root's combined archive, notice, task, matrix, campaign and
  policy regression passed **913 tests**, exit zero in **15.45 seconds**.
  Log SHA-256 is
  `362865d0be85e9cbcd82f1200c9cd2af5e6480ef3f09e2e95cae8e395e4cf68e`;
  JUnit SHA-256 is
  `c666ae20abcd4c41b6973a66adab4cdea13f3fa9b744958490e0201c221ba5cc`.
  No owned test process or diff-check error remained. New full Non-live and
  failed-only C06/C08/C09/M05 validation remain required, followed by final
  full acceptance and identical verify-only. The C03 import notice path is
  unaffected; its two passing version units need no failed-only rerun.

- **Complete failed-only batch — 2026-10-02:** frozen `4d2c121` completed
  Non-live **12800 passed / 119 skipped / 27 deselected**, exit zero in
  **834.11 seconds**. Log SHA-256 is
  `d3f8f529fbbb31ea5c47366a69d639a3fefb631e14a8233c13e9ab034a79f2ed`;
  JUnit SHA-256 is
  `452f0bd863dd4c11294aa7b762438a7c9d8c8e66da4e8c0adf30871925be5803`.
  The Skill and Program inputs remain byte-identical to `b4fd348`.
  Root `expansion-failed8-4d2c121-luna-high-r1-cli1592` then completed all ten
  selected units: **2 Agent PASS / 7 FAIL / 1 separate boundary**, zero pending
  and no early stop. Both C03 version units formally passed. Six other units
  completed the correct business effect with passing independent assertions;
  their only failed gate was the notice interpretation. C08/2022 remained a
  genuine safe-incompletion FAIL after omitting the required metadata scope.
  #147 consolidates uniquely attested target references, before-state versus
  prospective point deltas, and compatible curve units; it must preserve all
  provenance and wrong-owner/extra-change negatives. Original FAILs remain
  frozen without verify-only or regrading. The launcher ran once, exited 1,
  was unloaded and left an empty scoped process set. All ten source hashes and
  mtimes remained unchanged and all trusted actors closed; two PASS projects
  were removed, seven FAIL projects plus the boundary stayed quarantined.
  Independent evidence review rehashed **1473 artifacts / 53908601 bytes** and
  seven metadata seals. Exact units, attribution and usage are in
  `../research/integration-expansion-failed-rerun-4d2c121-2026-10-02.json`.
  Fresh failed-only reruns and final thirteen-Agent-unit plus boundary acceptance
  remain pending after the next reviewed, gated notice candidate.

- **Partial failed-only root and archive stop — 2026-10-02:** frozen
  `b4fd348` passed Program **6094 / skipped 2**, exit zero in **290.39 seconds**
  (log SHA-256 `85bbc3ca79200477745353e67a3889a0f6d8bd74584bd53e773727718d40c02b`),
  then sequential SFX owned-copy proof on 2022.1/2025.1, **one PASS each** in
  **28.66/27.73 seconds**. Each passed seven independent assertions; an
  independent evidence review validated 49/49 and 53/53 Gateway checks,
  single goal execution, both prepared/PENDING → final/PASS lifecycle histories,
  unchanged full source hashes/mtimes/tree metadata, closed actors, deleted
  copies and empty process scopes. Complete Non-live then passed **12780 /
  skipped 119 / deselected 27**, exit zero in **850.13 seconds**. Log SHA-256
  is `bc0eac4160b281085e222a5cd0706346a58203264498e1c3967df2fb394e8bd4`;
  JUnit SHA-256 is
  `f19d78b1bdf6fb900863782aa4e799c137892bf6bce6a1999a4746fb8170c89b`.
  Fresh root `expansion-failed8-b4fd348-luna-high-r1-cli1592` then stopped
  after five of ten units. Matrix: **2 Agent PASS / 2 FAIL / 1 boundary /
  5 pending**. Canonical campaign: **2 Agent PASS / 1 FAIL / 1 BLOCKED /
  1 boundary / 5 pending**. C08 safely stopped at an undisclosed Core role;
  C09's invalid `--include effects` query was authenticated and rejected
  before dispatch, but archive replay rejected that malformed-read evidence.
  #146 repairs canonical failure evidence without granting Agent PASS.
  The one-shot launcher ran once, exited 3, was unloaded, and left no scoped
  process. All five source hashes and mtimes remained unchanged; both PASS
  copies were removed, both failures and the boundary were quarantined.
  Independent reviews rehashed **553 artifacts / 18489646 bytes** and seven
  metadata seals. Exact partial results and usage are in
  `../research/integration-expansion-partial-b4fd348-2026-10-02.json`.
  This incomplete root remains frozen without verify-only or regrading.
  All unused launchers remain unused; new failed-only and final full acceptance
  still require new roots after the reviewed harness repair and regression.
  #146 now validates only an authenticated terminal `query-object` parser
  rejection, with exact rejection reason, null runner/payload evidence and an
  actual public parser exit 2. Admitted commands and all provenance, ordering,
  reconciliation and source guards retain their prior checks. The reproduction
  failed first; the combined archive/task/matrix/campaign/policy selection passed
  **674 tests**, exit zero in **16.28 seconds**. Both independent review axes
  are clear. Log SHA-256 is
  `0f607b9c9bf3e9d5c6ce0688e5af77e416a2155ee591c632a809a2dcc1a87173`;
  JUnit SHA-256 is
  `92c3caff2970eac2543886576a6ea30ddef1f3421bd510405409ed4a84608a5f`.
  Skill, CI and Program inputs remain byte-identical to `b4fd348`; complete
  Non-live and new Fresh evidence remain required for this archive candidate.

- **Completed archive repair and native SFX proof — 2026-10-02:** frozen
  `dcb747c` completed Non-live **12779 passed / 119 skipped / 27 deselected**,
  exit zero in **869.50 seconds**; JUnit has zero errors/failures. Log SHA-256
  is `fca49e4b849dcfc4424274a8b33d63c1a36cc016e8b7e629b3ef9786955912b7`;
  JUnit SHA-256 is
  `e5999574c388e4d13eff6a0742fe7dd48cb8a232e50ea179ca8b5c2000f9fa79`.
  #144 is closed after both independent reviews and complete regression.
  The new SFX real node first failed before mutation because its `config-set`
  invocation used invalid positional arguments. Reviewed test-only `7a202e5`
  corrects the public policy flag without changing Program/runtime/harness inputs.
  On that candidate, sequential owned-copy proof passed **2022.1: 1 passed /
  32 deselected, 24.82 seconds**, then failed **2025.1: 1 failed / 32 deselected,
  25.45 seconds** after one authorized goal Execute. The strict verifier retained
  five failed media-placement/hash assertions: Source-bound imports flattened
  the Originals destination and collided on `Hit.wav`. Runtime repair #145
  must preserve both sealed destinations and Source configuration; never weaken
  those guards or reuse the failed sandbox. Both full source hashes, project
  mtimes and tree metadata were unchanged, both trusted actors fully closed,
  the PASS copy was deleted, the FAIL copy quarantined, and hosts cleaned with
  no residual process. These are real Gateway proofs, not Fresh Agent results.
  No new Fresh campaign started; all prepared launchers remain unused. After
  #145 is reviewed and gated, rerun both real versions on new copies before
  failed-unit Fresh reruns and final thirteen-Agent-unit plus boundary acceptance.
  #145 retains each live-attested `originalsSubFolder` alongside its Source GUID;
  no verifier, public contract, or older native shape changed. Five-version
  preparation reproduced one 2025 RED; the related focused selection passed
  **540 tests**, exit zero in **8.23 seconds**. The old failed outcome still
  rejects all five original assertions. Both independent review axes are clear.
  Log SHA-256 is
  `5b98d5a653efbc44f79fe45fa46f625779d3bc39e1c40f064fd748fd19476207`;
  JUnit SHA-256 is
  `13809a91016e93182a3bf19fa206f8968f8642eb5ee1a3ea64ed13bd9e7dd226`.
  Freeze and complete Program first, then new sequential owned-copy native proof.
  Complete Non-live before the next Fresh root if both native proofs pass.

- **Stable-candidate gates — 2026-10-02:** frozen `ebdc769` passed the
  fixed five-version Program gate: **6093 passed / 2 native-Windows skips**,
  exit zero in **288.27 seconds**. Log SHA-256 is
  `5de2a493242173d611edf4707efabb208f091068f96aab8c08c49531ade114b9`.
  Complete Non-live then retained **12770 passed / 4 failed / 119 skipped /
  27 deselected**, exit one in **835.08 seconds**. All four failures are in
  the synthetic C08 archive fixture, at the new closed post-Preview notice
  attestation. Its old fixture lacks prepared-request/dispatch and independent
  identity/source fields and an exact point/source/shape notice. Repair #144
  updates synthetic evidence only; production checks and real frozen records
  remain unchanged. Log SHA-256 is
  `8ef69ebd223c9be6484dd7106b2f2d3bbd4ad8fe6d548671b8521afd5f62f393`;
  JUnit SHA-256 is
  `076ab93c0039df0739b27d95d08b8c38c21b1553c686f68e183766d125fcefe2`.
  No real or Fresh process started. The new failed-only launcher is prepared
  but unused; require repaired, reviewed Non-live and sequential SFX proofs
  before bootstrapping a new campaign root.
  Fixture repair #144 reproduced **4 failed / 79 passed**, then passed all
  **88 archive tests**, including five new internally sealed semantic negatives.
  Combined archive/attenuation/notice validation passed **466 tests**, exit zero
  in **3.08 seconds**. Log SHA-256 is
  `cf73e8913fa8b2e2bb561c7ce27c082b61813ecc0d86a8753f44aa4b7cc46c94`;
  JUnit SHA-256 is
  `cceb803ac44b854d77c3cc323a220a147452f13763ffd8d51da10efed7d79d9d`.
  The production Skill and semantic support modules remain byte-identical to
  `ebdc769`; repaired complete Non-live evidence remains required.

- **Resumed repair batch — 2026-10-02:** the user explicitly resumed after
  the requested pause. Consolidated #141–#143 repairs received both independent
  review axes. Spec findings for an extra curve-field/deletion claim and a
  second explicit reference owner were reproduced, repaired, and rechecked;
  neither review has a remaining concrete finding. The combined focused gate
  passed **1328 tests / 9 native-Windows skips**, exit zero in **10.14 seconds**.
  Log SHA-256 is `4d342280ea5ac7f3fab7255100a72dd36ec18d853e4ceac2e706f2a5bfe2f491`;
  JUnit SHA-256 is `1de6c115bb761422a77c7e011c1d1d7792f73b1938fe46716fc0d61d0cd06fcc`.
  These checks do not grant live or Fresh acceptance. The new owned-copy SFX
  node is still unrun. Freeze this reviewed candidate, complete Program and
  Non-live, then use its exact `-k` selector for sequential 2022.1/2025.1
  real proofs; the driver adds default nodes to a bare-path invocation.
  Rerun the eight failed Agent units plus the directly affected 2022 C06 control
  and separate M05/2022 boundary before final complete acceptance. Preserve both
  frozen FAIL roots and all unrelated user drafts; no historical FAIL is regraded.

- Frozen failed-only root `expansion-failed9-c39b728-luna-high-r1-cli1592`
  completed all ten selected units: **1 Agent PASS / 8 FAIL / 1 separate
  BOUNDARY_PROVEN**, zero pending and no early stop. Independent audit rehashed
  **1602 artifacts / 60832898 bytes** and eight metadata seals. All source full
  hashes and mtimes were unchanged; the PASS copy was removed and eight FAIL
  copies plus the boundary copy remained quarantined. The launcher ran once,
  exited 1, was unloaded, and left zero scoped processes. Agent work totalled
  **1431.191725 seconds / 11 turns / zero slow cases**. All nine Agent units
  executed once and attempted Verify once. Seven units have complete passing
  business-oracle assertions, including six formal notice FAILs; both C03
  after-states remain unavailable and receive no business PASS credit.
  Exact evidence and usage are in
  `../research/integration-expansion-failed-rerun-c39b728-2026-10-02.json`.
  The next consolidated repairs are #141 (2025 SFX Source targeting and proven
  native-result omission), #142 (closed curve notice validation), and #143
  (coherent owner/numerical/action/polarity notice evidence). No FAIL root was
  replayed or regraded; new failed-unit reruns and final full acceptance remain
  required after those reviewed repairs.

- Candidate `c39b728` passed full Non-live **12587 / skipped 118 /
  deselected 27**, exit zero in 838.44 seconds; JUnit has zero errors/failures.
  Log SHA-256 is `07e02a6c2c726f2842b5c71f51924f54a7d836dbfd9dab753ac3c87c4c5a71e2`;
  JUnit SHA-256 is `935ad4a3d45b75877405d33c0bb5a52985094950b2d46c43d34d37793c77aa01`.
  The Skill/semantic/CI inputs remain byte-identical to `f16ab1c`, whose Program
  evidence remains a component PASS. Sequential 2022.1/2025.1 smoke checks
  completed in 6.260607/7.485409 readiness seconds and cleaned both copies with
  unchanged source hashes and mtimes. Those checks establish readiness only.

- Consolidated candidate `f16ab1c` completed the fixed five-version Program gate:
  **6043 passed / 2 native-Windows skips**, exit zero in 289.11 seconds;
  log SHA-256 `d974e6ea2ce988e257081978c8ae5fbb6fe45a8d19e0bf3b6400a11873666ebf`.
  Its full Non-live run preserved **12586 passed / 1 failed / 118 skipped /
  27 deselected** in 824.44 seconds. The sole failure was the old manifest
  cardinality assertion (195 instead of 197 after two new files were enrolled),
  not a runtime failure. The correction updates that count and explicitly
  requires both new files; its focused file passed **43 / skipped 11 native
  Windows executors**. Non-live log SHA-256 is
  `cdbbf24d7a1e32d6832627a7e7cc17eaa1353ead3c873856713baeed32e1ccce`;
  JUnit SHA-256 is
  `25194f79c96778ee1459637cb4aa767605980f7b8e88c43d21770bcadfa4d5d8`.
  A new all-green Non-live run remains required. No Fresh root was launched;
  the prepared `f16ab1c` launcher is retained unused. The correction changes
  only a Non-live test and this checkpoint, leaving Program inputs, Skill,
  suite, runner, and semantic harness unchanged.

- Consolidated initial-batch repairs are tracked as children #137–#140 of #108
  and native blockers of acceptance #122: existing SFX source/Originals
  preservation, attenuation choice disclosure, expansion policy instructions,
  and uniquely attested contextual notices. The expansion-only instruction
  construction now distinguishes ask, allow, and read-only policies; historical
  defaults and custom bases remain unchanged. Its focused construction/wiring
  selection passed 25 tests after the new allow-mode reproduction failed first;
  the full harness file passed 410 tests and skipped nine native-Windows proofs.
  The consolidated repairs then passed **1441 focused tests / 9 native-Windows
  skips in 27.82 seconds**, with zero JUnit failures or errors. Both independent
  review axes are clear after fixing the notice extra-change finding; the final
  notice file passed 241 checks. The two new public unit files are enrolled in
  the fixed Program gate. Generated interface-depth inventory `--check` passed
  without resource changes. The focused log SHA-256 is
  `a644ea7437f0f3b3dbcb0cf01ff0e22611e1bc7eb022ec90200a032e278a6fe5`;
  JUnit SHA-256 is
  `01993c8ff779ce94725d467d8fd30eb68a7d40956cb5157068829ea061fbbdab`.
  These are program checks, not new Fresh or live acceptance. Full Program and
  Non-live gates, nine failed-unit reruns, and final complete acceptance remain
  pending on the next frozen candidate. Original FAIL records are unchanged.

- Initial full macOS acceptance on frozen `977e71e` completed **all fourteen
  units: 4 Agent PASS, 9 FAIL, and 1 separate BOUNDARY_PROVEN**, with no early
  stop, pending unit, same-root retry, or verify-only replay. Independent audit
  rehashed **1931** artifacts and six campaign metadata seals. Source full hashes
  and mtimes remained unchanged; four PASS copies were removed and nine FAIL
  copies plus the boundary copy stayed quarantined. All fourteen oracles closed;
  failure reconciliation reaped every owned child. The job was unloaded and
  scoped processes were empty. Actual Agent work totalled **1960.95 seconds /
  16 turns / zero slow cases**, with eight executions and eight verifications.
  Exact records and attribution are in
  `../research/integration-expansion-initial-acceptance-977e71e-2026-10-02.json`.
- Consolidation must distinguish the actual SFX source-placement/media collision
  in C03/2022, undisclosed curve choices in both C08 units, the expansion's
  unconditional developer confirmation instruction, three correct executed
  effects rejected by contextual notice grammar, and two safe but incomplete
  Agent input/discovery workflows. No original FAIL is promoted. Complete all
  reviewed repairs first, rerun nine failed units, then rerun the full thirteen
  positive units plus the 2022 M05 boundary on one candidate. Acceptance remains
  incomplete; the source-safe initial batch is preserved as failure evidence.

- The final model pilot completed **nine tasks / twelve turns** on `977e71e`.
  Luna high and Sol medium each passed all three cases and identical verify-only;
  Luna medium passed two and retained one genuine continuation-copy FAIL, despite
  correct business effects. All nine independent business oracles passed, but the
  failed Medium root stayed frozen without verify-only. Independent reviews
  rehashed **882** artifacts and eighteen metadata seals and confirmed the exact
  lifecycle, usage, and separate failure attribution. The formal model is now
  frozen as **GPT-6 Luna / high / default tier**, following the user's Luna
  preference, with **600-second cumulative Agent / 420-second slow / 180-second
  startup** limits and no same-root retry. No USD-price advantage or long-term
  success rate is claimed. Exact settings and comparison are in
  `../research/integration-expansion-model-selection-2026-10-02.json`.
  Full 2022.1/2025.1 acceptance remains pending: thirteen positive Agent units
  plus the separately credited M05/2022 runner-only boundary on one candidate.

- Consolidated notice-evidence candidate `977e71e` passed **344 focused tests**
  and Non-live **12360 / skipped 118 / deselected 27**, exit zero. Its public Skill
  and Program inputs remain byte-identical to `cf94158`; no new Program rerun is
  claimed. Fresh failed-only C06 passed for both Luna high and Sol medium, each
  followed by identical verify-only with no extra Fresh task or turn. Independent
  audit rehashed **190** artifacts and twelve metadata seals; all seven business
  assertions passed per unit, each executed once, sources unchanged, PASS copies
  deleted, and all four jobs unloaded. Exact proof and usage are in
  `../research/integration-expansion-consolidated-notice-proof-2026-10-02.json`.
  The complete matched six-task selection is now running on frozen `977e71e`;
  model selection and final acceptance remain pending. Original FAILs remain frozen.

- The complete matched `86e23cd` pilot finished **six tasks / eight turns**:
  each model passed C01/M01 and retained a C06 notice FAIL, for **4 PASS / 2 FAIL**.
  All six independent business oracles passed. Both C06 notices were precise and
  timely; Luna's delta plus full result produces redundant tuple mentions, while
  Sol's current curve and expected midpoint span clauses. These are grader
  defects, not observed mutation, preservation, or advance-notice failures.
  The two mixed roots were frozen without verify-only; all **740** artifacts and
  twelve metadata seals were independently audited, sources unchanged, PASS
  copies deleted and FAIL copies quarantined. Both jobs were unloaded.
  #134 was reopened for a consolidated repair, then both failed units and a
  complete new-candidate selection must run. No model or final acceptance is
  selected. Exact outcomes, usage, timing and attribution are recorded in
  `../research/integration-expansion-matched-pilot-86e23cd-2026-10-02.json`.

- Coherent RTPC notice-context repair `86e23cd` passed **321 focused tests** and
  Non-live **12337 / skipped 118 / deselected 27**, exit zero. The packaged Skill,
  CI, unit tests, and maintenance tree are unchanged from `cf94158`, whose Program
  result remains component evidence rather than a new-candidate rerun claim.
  Fresh Luna C06 passed in **112.12 Agent seconds**, then identical verify-only
  passed without another Fresh task or turn. Independent audit rehashed **95**
  artifacts and six metadata seals; seven business assertions passed, the notice
  preceded the sole execution, source full hash/mtime stayed unchanged, and the
  PASS copy was deleted. Both jobs were unloaded. Exact proof and usage are in
  `../research/integration-expansion-context-repair-proof-2026-10-02.json`.
  The complete matched six-task model pilot is now running on frozen `86e23cd`;
  no model selection or final acceptance is claimed yet. Original FAILs remain frozen.

- Reviewed notice/disclosure candidate `cf94158` passed Program **5888 / skipped 2**
  and Non-live **12309 / skipped 118 / deselected 27**, both exit zero, then
  2025 smoke in **4.2055 seconds** with unchanged source and clean deletion.
  Its predecessor `d8bcb43` failed one Program inventory-seal check; the existing
  generator and independent review proved only the five `audio.import` contract
  hashes and aggregate/inventory seals changed. The failed gate remains recorded.
  Exact reports are in `../research/integration-expansion-notice-disclosure-gates-2026-10-02.json`.
- Fresh Luna failed-only rerun completed **1 PASS / 1 FAIL**. M01 passed using
  the existing structure-only import declaration; C06 still failed visible-notice
  grading despite its precise advance midpoint update and seven true independent
  business assertions. Its identity, effect, preservation, and shape evidence
  span notice clauses and an earlier visible plan, which the current matcher
  does not accept. All **304** sealed artifacts were rehashed; sources unchanged,
  PASS copy deleted, FAIL copy retained, job unloaded and scoped processes empty.
  The mixed root was frozen without verify-only. #134 context repair, the complete
  matched model pilot, and final acceptance remain pending; no model is selected.
  Exact evidence is in `../research/integration-expansion-failed-rerun-cf94158-2026-10-02.json`.

- Frozen `919043f` passed Program **5888 / skipped 2** and Non-live
  **12282 / skipped 118 / deselected 27**, both exit zero, then matching
  2025 smoke in **4.3971 seconds** with clean sandbox deletion. Exact reports
  and digests are in `../research/integration-expansion-context-copy-gates-2026-10-02.json`.
  Failed-only reruns completed four units: Sol C01/C06 PASS plus identical
  `--resume --verify-only`; Luna C06/M01 FAIL. All **520** sealed artifacts
  were rehashed, sources unchanged, PASS copies deleted and FAIL copies retained,
  jobs unloaded with no scoped residual process. The initial malformed launcher
  exited in argument parsing before creating a campaign or starting any task;
  its logs/plist remain preserved and replacement launchers passed the production
  parser. This startup fault receives no model or case credit.
- Remaining #134 work covers the accurately stated scalar midpoint update
  rather than mandatory repeated property labels/coordinate tuples; its seven
  independent business assertions passed. #136 clarifies the existing public
  import declaration's structure-only row exception and earlier-parent IDs.
  Luna M01 made five successful reads/bindings but stopped before declaration,
  Preview or execution after interpreting incomplete media-completeness guidance.
  No separate creation capability is needed. Full model comparison and final
  acceptance remain pending; no original FAIL is promoted. Exact rerun evidence
  is `../research/integration-expansion-failed-rerun-919043f-2026-10-02.json`.

- Consolidated #134/#135 passed **709 focused tests / 9 native Windows-only
  skips** in 3.79 seconds, exit zero. Each seam passed independent Spec and
  Standards review after fixing preservation/shape-negation findings.
  Unique existing RTPC context can support an accurate point delta or an
  attested relationship GUID; numeric parsing recognizes U+2212 without
  changing signed-value checks. Wrong identity, ambiguous context, wrong
  points/shape and affirmative protected changes remain rejected.
  Expansion-only authenticated read interleaving retains the latest exact
  Draft binding; strict historical defaults, positional receipts and stale/
  changed continuation controls remain unchanged. The new candidate still
  requires broad gates, failed-case reruns and the full selection afterward.

- Frozen `0997d20` completed Program **5888 passed / 2 skipped** and
  Non-live **12197 passed / 118 skipped / 27 deselected**, both exit zero;
  matching 2025 smoke was ready in **3.3797 seconds** and cleaned its sandbox.
  Exact reports/digests are in `../research/integration-expansion-notice-read-gates-2026-10-02.json`.
  Its entire matched six-task batch completed: Luna C01 and Sol M01 PASS;
  both C06s, Luna M01 and Sol C01 FAIL, without BLOCKED or pending units.
  All **982** sealed artifacts were independently rehashed; full source hashes
  and mtimes were unchanged, PASS copies deleted and FAIL copies quarantined,
  both jobs unloaded and no scoped process remained. No model is selected.
- Read-only diagnosis identifies three concrete-notice false negatives:
  Luna C06 uses the uniquely attested association GUID, Sol C06 describes the
  accurate before-to-after midpoint delta in its uniquely bound relationship
  context, and Luna M01 uses mathematical `−6` rather than ASCII `-6`.
  Independent `verify_c06` checks (seven per case) and `verify_m01` (six)
  passed separately from Gateway assertions. Sol C01's thirteen admitted,
  successful authenticated receipts are rejected only by an immediate-next-
  Draft copy assumption: six bounded preservation reads precede an exact
  unchanged declaration continuation. It stopped after Preview without execution.
  Repairs #134/#135 address contextual notices/numeric formatting and exact
  copy validation across authenticated reads. These original FAILs remain
  frozen; no verify-only or regrading was performed. Exact records are in
  `../research/integration-expansion-context-notice-pilot-2026-10-02.json`.

- Consolidated #131/#132/#133 repairs passed **711 focused tests / 9 native
  Windows-only skips** in 4.98 seconds, exit zero, with independent Spec and
  Standards review on each seam. Natural import `更新`/`update` notices are
  accepted while missing advance notices remain failures; concise general
  Preview/notice/Execute guidance stays below the existing instruction ceiling.
  Historical terminal rejection replay now proves the exact unchanged bound
  Draft without granting business PASS. New owned-project read scopes use the
  public Gateway `MAX_QUERY_TAKE=1000`, preserve explicit historical/default
  64-row scopes and byte/call/source fences, and reject non-boolean ownership
  flags. No packaged Skill, matrix isolation bypass or frozen regrade was added.
  A new frozen candidate's broad gates and fresh model runs remain required.

- The frozen `122eb09` pilot retained three Luna-high ordinary FAILs, all at
  `visible_preview_notice`. C01 supplied a concrete post-Preview notice, but
  the Chinese verb `更新` was absent from the import effect alternatives.
  C06 and M01 genuinely had no notice between Preview and Execute; their final
  summaries do not substitute for advance notice. Repair #131 addresses the
  natural-wording false positive and clarifies the formal task instruction's
  required Preview/Execute notice, without weakening authorization or oracles.
- Sol-medium C01 obeyed a terminal rejection before Preview: requested
  `--max-results 100` exceeded the runner-owned 64-row limit. The frozen runner
  result is FAIL. Subsequent inspection established that this 64-row limit was
  not visible to the Agent; its public query schema instead allowed 1–1000,
  and the Skill included a normal 100-row example. This is a benchmark admission
  mismatch, addressed separately by #133, rather than fair evidence of an Agent
  cap violation. Unsupported archive replay of the authenticated rejected
  owned-project read after an accepted exact Draft binding caused a systemic
  stop and consolidated BLOCKED, leaving Sol C06/M01 unattempted. Repair #132
  adds this safely isolated historical FAIL shape; it does not increase old
  sealed budgets or reinterpret the original result. Both jobs were unloaded, no scoped process remained,
  sources were unchanged and failed copies remain quarantined. All **790**
  sealed artifact contents were independently rehashed. Exact original results
  are in `../research/integration-expansion-archive-repair-pilot-2026-10-02.json`.
  The six-task comparison is incomplete and no model is selected.

- Frozen `122eb09` completed Program **5888 passed / 2 skipped** and
  Non-live **12156 passed / 118 skipped / 27 deselected**, both exit zero.
  The matching 2025 smoke reached readiness in **4.1306 seconds** and removed
  its clean sandbox. Exact completed reports and digests are in
  `../research/integration-expansion-archive-seal-gates-2026-10-02.json`.
  The matched-model roots used the same candidate and pinned CLI 0.159.2,
  with Luna-high scheduled first. These gates alone provide no Fresh
  business acceptance or model-selection credit.

- Native follow-up candidate `78c3587` passed all nine selected nodes with
  final full-source-content protection and cleanup evidence. The independently
  checked evidence summary is `../research/music-native-maintenance-evidence-2026-10-02.md`;
  #129 is closed. This remains native maintenance/investigation evidence.
- Its new Luna-high Fresh root completed C01's two-turn business workflow in
  **163.208 Agent seconds**, but the mandatory archive isolation check stopped
  the matrix. The consolidated result remains C01 BLOCKED, C06/M01 PENDING;
  the original root receives no formal campaign PASS credit and was unloaded.
  Repair #130 corrects the harness-only transaction seal reader's legacy
  six-field project guard expectation to the current exact nine-field producer
  contract, including both fingerprints and closed mode/postcondition checks.
  The old contract remains strict. TDD reproduced two failures before repair;
  focused seal/CLI/archive regression then passed **173 tests** in 2.35 s.
  Original evidence is frozen; a new candidate/root and matched model pilot
  are required. No packaged Skill or matrix isolation check is bypassed.

- Candidate `b23011f` completed Program **5888 passed / 2 skipped** and
  Non-live **12126 passed / 118 skipped / 27 deselected**, both exit zero.
  Exact logs and digests are recorded in
  `../research/integration-expansion-compact-catalog-gates-2026-10-01.json`.
  Its first 2022 native follow-up had three sealed read-investigation PASSs
  and one Transition CALL pass followed by a sealing error: mandatory
  `verifier_strength` was absent. That Transition attempt receives no acceptance
  credit; its log, transactions and copied project remain retained.
- Repair #129 supplies the precise scalar/XML/media verifier label and the
  bounded all-source content guard described below. Its combined actual
  finalizer, category and Transition regression passed **54 tests** (3.90 s).
  Independent Spec and Standards reviews found no actionable issue. Fresh
  owned-copy native reruns remain required; no historical outcome is upgraded.

- Candidate `ae3d355` completed Program with **9 failed, 5879 passed,
  2 skipped**. The nine old catalog consumers expected repeated row fields;
  the producer's compact contract and all schema obligations remain unchanged.
  A tests-only static-directory expansion helper updates the three affected
  files without weakening host/version, safety, refusal, native-field, or
  schema-reachability checks. Focused validation passed **509 tests**;
  independent Spec and Standards reviews found no actionable issue. The
  original full-gate failure is retained in the catalog-consumer gate record.
  A new complete gate is required before real follow-ups or Fresh execution.

- Frozen `4d74ebb` passed Program **5888 / skipped 2** and Non-live
  **12082 / skipped 118 / deselected 27**. The matching 2025 smoke became
  ready in 4.10 seconds and cleaned its copied sandbox. Exact gate digests
  are in `../research/integration-expansion-entry-repair-gates-2026-10-01.json`.
- Its matched CLI 0.159.2 pilot completed all six units as ordinary FAIL,
  each after `operations`, without a Draft, Preview, or execution. The 918
  sealed attempt artifacts were independently rehashed. Source hash/mtime
  protection and retained failed copies were verified; both launch jobs are
  unloaded and scoped processes are gone. Model selection remains unresolved.
  Correcting the footer instruction alone did not remove the directory stop;
  actual model-visible truncation or budget remains unproven. Timings, usage,
  and raw digests are in the entry-repair pilot record.
- Scoped repair #128 factors ordinary directory templates and common metadata
  while preserving all identities, descriptions, host/version exceptions,
  routing, and safety distinctions. Packaged offline CLI output is 15–25 KiB
  across the five lanes; 2025 retains 33 named operations and 136 routes in
  25,432 bytes. Detail output is unchanged. Independent Spec and Standards
  reviews found no actionable issue; the combined focused regression passed
  **452 tests**. A new frozen candidate, broad gates, and fresh evidence remain
  required. No old FAIL receives new acceptance credit.

### Music investigation follow-ups

Historical native category records hash `.wproj`/`.wwu` content and separately
record whole-tree metadata; they do not establish all-source/media byte integrity.
Saved copy metadata uses `bounded-wproj-files` (one file in the inspected audit),
which is a separate, narrower proof. Formal Fresh lifecycle full-source hashes
remain valid. Repair #129 adds bounded all-source content hashes before launch
and after shutdown, with explicit scope/file/byte counts before final PASS; no
old raw record, digest, outcome, or failed copy is upgraded or changed.

- Six platform-aware read investigations completed on `4d74ebb`, with source
  project/workunit content hashes, project mtime, and whole-tree metadata
  unchanged; scoped cleanup was proven. The two
  fade property-state requests now reach actual live-name ambiguity rather
  than missing-platform input errors; they do not establish enabled state or
  native physical-time units. Complete arrangement/order claims remain blocked.
- The 2025 reference goal stopped before any Draft because its legacy music
  Originals are absent from the committed fixture. Its original FAIL and copy
  remain retained. The source WWU has 70 source identities sharing 67 WAV paths.
  The reviewed main-only preparation copies an existing hash-pinned repository
  WAV into missing owned paths, preserves source/XML/existing files, and retains
  actual media-hash assertions. It generates no audio or new Gateway capability.
- A reviewed populated Transition probe uses the live-attested
  `PlaySourcePostExit` boolean, one exact edit transaction and a separately
  approved save. Independent saved XML covers the 15-rule graph, fourteen
  siblings, meaningful order, references, fades, and protected media. It is
  scalar maintenance evidence only; full M04 and M06 remain false. Both new
  probes still need execution on a new frozen candidate. Native read results
  and the untouched failure are in the music-native-followups record.
- The preplanned fade-state meanings are now `time` and `offset` in the exact
  MusicFade/Mac scope. The four-field public fake regression passes **35 tests**
  and retains the original broad-name ambiguity as a negative control. This
  is no native enabled-state or duration-unit proof; those reads remain pending.

### Matched model pilot and shared entry repair #127

- Both official CLI 0.159.2 pilot halves finished their complete three-task
  selection on frozen `cc8707a`: Luna high **0/3**, GPT-6.1 Sol medium **0/3**.
  Five tasks stopped after `operations` claiming truncation; Luna M01 instead
  reached an invalid brace-less GUID binding rejected before dispatch.
  No task reached Preview or execution. Sources remained unchanged, failed
  copies remain sealed, both launch jobs are unloaded, and scoped processes
  are gone. The 920 attempt-artifact hashes were independently checked without
  invoking formal verify-only or changing a recorded FAIL.
- The operate reference requires a typed-container footer unconditionally,
  although ordinary `operations` returns complete JSON without that footer.
  Archived command stdout does not prove how much the model actually saw.
  Repair #127 narrows that instruction, preserves real-truncation stops and
  exact GUID grammar, and leaves Gateway output shapes and graders unchanged.
  The model choice remains unresolved; Luna medium is not yet eligible.
- Exact model settings, timings, usage, source guards, and artifact digests are
  in `../research/integration-expansion-matched-model-pilot-2026-10-01.json`.
  Review, regression gates, and a new frozen matched pilot remain required.

- Repair #127's producer-backed focused regression passed **93 tests** after
  two red regressions. Independent Spec and Standards reviews found no
  actionable mismatch. The revised instructions preserve actual truncation,
  missing typed-footer, invalid-GUID, and failure stops. Broad gates and fresh
  matched model evidence are pending; the original six FAILs remain unchanged.

### Completed pristine-Draft gate, native reads, and model prerequisites

- `cc8707a` completed Full Non-live: **12044 passed, 118 skipped,
  27 deselected**, exit zero (777.20 s). Source was clean and no owned test
  process remained. Exact digests are in the pristine-Draft gate record.
- Six music read investigations completed with project/workunit content hashes,
  project mtime, whole-tree metadata, and scoped cleanup unchanged. The 2025 nine-tuple references were readable; 2022's
  two unknown-property getters remain accessor boundaries. Missing-platform
  property-state requests were input errors; the main-only correction passed
  35 focused tests. Native units and authoritative ordering remain unproven.
- A separate existing-2025-reference goal uses the current closed setter and
  exact immutable Preview. Independent review repaired incidental Entry-order
  rejection and oversized failed evidence. Its 23 focused tests passed; real
  execution and complete workflow evidence are still pending.
- Delivery tickets #111 (M01) and #113 (C06) closed from their earlier two-version
  public Gateway goal evidence and current regression. This is not Agent credit;
  the other business/model/final-acceptance tickets remain open.
- On CLI 0.157.1, Luna high finished all three tasks as ordinary FAIL before
  Preview, each stopping at the approximately 44 KiB operations response.
  All failed copies/source guards were retained. Sol's three units were blocked
  before Agent action: that CLI rejected `gpt-6.1-sol` for ChatGPT auth.
- Official 0.159.2 was installed only in the managed ignored tooling directory,
  verified against its published archive hash. A disposable read-only no-tool
  availability probe returned READY on 6.1 Sol medium; it grants no semantic
  credit. Both pilot halves now require fresh roots with that same CLI.
  The managed formal candidate remains `cc8707a` while main-only follow-ups are
  reviewed; no old FAIL/BLOCKED root is resumed or regraded.

### Pristine rejected-Draft archive review

- The invalid-GUID terminal rejection now retains original FAIL/unprepared and
  false gates while proving ordered command receipts, the pristine started Draft,
  its authoritative versioned Gateway schema, no Preview/authorization/execution,
  unchanged reconciliation, and complete cleanup. Public GUID grammar is unchanged.
- Combined archive/CLI/task-runner/documentation validation passed **166 tests**.
  Independent Spec and Standards reviews are resolved. A read-only derived check
  of the original failed task retains FAIL and zero executions; all twenty task
  file hashes and mtimes remained unchanged. It was not a formal verify-only run.
- The reviewed candidate still needs its broad regression and new real roots.

### Priority music read-probe preparation

- Added three developer-owned, copied-project public Gateway read investigations
  for Playlist, existing-fade Transition, and Music Switch paths on 2022.1/2025.1.
  The XML witness retains fifteen rules and all nine condition tuples. No new
  Skill functionality, native client, playback, or Agent acceptance is included.
- Independent review corrected cap-completeness and 2022 missing-identity
  comparisons. Three fake public-dispatch regressions additionally prove current
  exact, relationship, and advanced query reply bounds. Focused validation passed
  **22 tests**; real probes have not yet run. Ordering and native time conversion
  remain unproven, not silently accepted.

### Completed receipt regression and subsequent model input failure

- Frozen `dd1ad71` passed Full Non-live: **11998 passed, 118 skipped,
  27 deselected**, exit zero (784.07 s). Logs/JUnit digests are in
  `../research/integration-expansion-read-receipt-gates-2026-10-01.json`.
- The next Luna-high C01 turn consumed 74.59 Agent seconds and failed before
  Preview: its object binding omitted the required GUID braces. Two independent
  code audits confirmed this is invalid public input, correctly rejected before
  dispatch. Preserve the original model FAIL and public grammar.
- The pristine mutable Draft and unchanged source/cleanup proofs need a narrow
  negative archive continuation check before remaining C06/M01 tasks can run.
  No immutable Preview, authorization, execution, or native change occurred.
  Full model comparison and final acceptance remain pending. Exact attribution
  and artifact digests are in
  `../research/integration-expansion-invalid-bind-pilot-2026-10-01.json`.

### Subsequent real pilot and receipt repairs

- `c566e85` Luna-high C01 entered a real isolated Codex task and consumed
  83.92 case-budget seconds. It stopped before Preview after the harness rejected
  the public `event-actions` preset's Gateway-owned 100-row bound. The source
  full hash and project mtime were unchanged; the failed copy remains quarantined.
  C06 and M01 were not started, so this is not a completed model comparison.
- `ad8a87c` accepts that sealed exact-Event read and validates its effective bound
  while keeping the 64-row case proof ceiling. Archive binding uses the existing
  closed runner resolver instead of literal shim paths. Original failed gates
  remain FAIL; accepted writes and uncertain outcomes retain their existing rules.
- Independent review found two proof gaps. `7c81406` binds commands and receipts
  positionally and requires completed rejected-read turns to cover every receipt.
  Three red tamper regressions preceded the repair; archive/CLI/task-runner
  validation passed 133 tests. Both review axes confirmed their findings resolved.
  The earlier combined expansion selection passed 425 tests. New broad regression
  and new frozen pilot roots remain required; original failures are not regraded.
- Sanitized pilot usage, failure attribution, and artifact digests are in
  `../research/integration-expansion-pilot-observations-2026-10-01.json`.
- `../research/music-expansion-oracle-gaps-2026-10-01.md` now records all nine
  saved Music Switch mappings and an existing-fade Transition with fourteen
  siblings. The original boolean target has neither a saved fade nor sibling
  rules. Official Help establishes UI seconds; native conversion and full live
  readback remain unproven. Research creates no additional execution credit.

- Root coordinator: GPT-6.1 Sol high. New implementation/review subagents:
  GPT-6 Luna max or GPT-6.1 Sol medium.
- The unexecuted pilot's Sol comparator is now GPT-6.1 Sol medium. Historical
  profiles remain unchanged.
- Generic progress messages no longer satisfy the expected-effect notice.
  Notice checks use the sealed Preview and independent pre-state; 21 focused
  regressions passed.
- Archive replay preserves negative timeout/no-JSON receipts and distinguishes
  consumed execution reservations from journal-proven dispatch. Five new red
  regressions preceded the repair; 22 focused archive tests passed afterward.
- The combined expansion-focused regression passed 282 tests on 2026-10-01.
  Frozen candidate `e8ab17c` then passed Program (5819 passed / 2 skipped)
  and Non-live (11766 passed / 117 skipped / 27 deselected).
- Real preflight at `e8ab17c`: 2025 had two setup/oracle-stability passes and
  five failures; 2022 had three setup passes, three failures, and one observed
  M05 capability boundary. All 14 final project/workunit-content, project-mtime, and tree-metadata guards
  and scoped-process cleanup checks passed. This is not Agent/business PASS.
  Durable records are summarized in
  `../research/integration-expansion-preflight-2026-10-01.json`.
- Scoped repairs cover attenuation read tokens (#125), versioned EffectSlot
  ownership, Stinger owner membership and unordered-list normalization,
  live Time.Max fixture points, and bounded failed-verification summaries.
  C01 now probes unsplit Event import and sets Volume separately; the original
  split-layout unmet Event effect stays tracked in #126.
- The combined repaired fixture/oracle/attenuation focused gate passed 429
  tests. New frozen real reruns, Fresh pilot, and final acceptance remain.
- A subsequent review confirmed failure-classification and post-failure
  readback gaps. Their expansion-only repair is committed in `78234f6`; no
  timeout, infrastructure block, or uncertain execution may be promoted to PASS.
- Tickets #109, #110, #123, and #124 are closed from their scoped evidence;
  business and final acceptance tickets remain open.

## Subsequent repair checkpoint — 2026-10-01

- Attenuation preparation passed on both versions after removing unsupported
  binding-role flags; #125 is closed from its getter repair and real metadata
  evidence. The production Program gate at `c626f94` passed 5884 / skipped 2.
- C01's bounded read diagnostics proved that Wwise created its Event but
  normalized hyphens to underscores in the Event name. Choosing the stable
  fixture name before import (`ca22052`) passed strict setup/verification on
  both versions; #126 is closed as a fixture diagnosis, not an import rewrite.
- Developer-owned public Gateway goal probes passed M01 music import and C06
  existing RTPC update on both versions. They approved the immutable Preview
  before authorization and execution, then required all independent after-state
  assertions. The first M01 probe's type-tag approval failure remains frozen;
  `90bddc0` accepts the evidenced spaced Music type tags.
- Independent review identified three harness defects: lost rejected-Preview
  FAIL evidence, discarded meaningful EffectSlot order, and premature batch
  termination for isolated uncertain outcomes. The repairs preserve exact
  negative classifications and keep execution prohibited after rejection.
  C09 now seals the owner's slot sequence separately from incidental read-row
  order. Expansion batches continue only after source and cleanup isolation is
  proven; historical profiles retain their previous behavior.
- The combined current expansion/metadata focused gate passed **504 tests**.
  The full 2022 fixture-preflight selection at `f9966f3` passed its seven pytest
  nodes: six prepared baselines plus the separate M05 capability boundary.
  Neither that boundary nor a prepared baseline grants Agent business PASS.
- Original failed roots, source protection, cleanup, and narrow goal results
  are recorded in `../research/integration-expansion-native-followups-2026-10-01.json`.
  That file covers 19 failed-only/native-goal follow-up lifecycle records and
  14 complete-preparation lifecycle records. The 2025 full preparation at
  `2732ac9` passed all seven nodes. All 14 full-preparation project/workunit content hashes,
  project mtimes, whole-tree metadata, and scoped-process cleanup checks passed;
  their PASS copies were deleted. This is not a final Fresh campaign.
- `../research/music-expansion-dispositions-2026-10-01.md` defines three full
  structural oracles, Chinese allow-mode case drafts, version-specific gaps,
  and four minimal follow-up scopes. Scalar maintenance is not full Playlist,
  Transition/fade, or Music Switch acceptance. Those tickets remain open.
- Final Non-live regression, the six-task model pilot, final Fresh acceptance,
  and identical verify-only are still pending.
- A final continuation review added complete archive replay before starting
  the next case, explicit trusted-oracle closure evidence with bounded
  post-shutdown reaping, and isolation proof for the last case of an abnormal
  prefix before any pending suffix can resume. The combined focused gate
  passed **515 tests** after these repairs. Partial archives and unproved
  cleanup remain systemic stops; ordinary isolated negative results continue.
- The first final Non-live attempt at `1e0783d` was interrupted and receives no
  PASS credit: CI-wrapper tests inherited the outer `WAAPI_TEST_PYTHON`, bypassed
  fake Poetry, and recursively started a real pytest run. Owned group 10379 and
  its seven processes were terminated; no owned test process or tracked source
  change remained. Its log and `abort.json` stay in
  `expansion-nonlive-20261001-final-r1`. Fake CI environments now exclude that
  host override; the two affected files passed 67 / skipped 11 with an explicit
  pinned interpreter. A new full gate root is required.
- The next full Non-live attempt at `753d721` completed with 11924 passed,
  19 failed, 6 errors, 118 skipped, and 27 deselected (810.05 seconds). It is
  retained as a FAIL, not final acceptance. Twenty failure/error observations
  came from unhydrated local Git LFS fixtures: expanding 32 locally cached
  objects cleared all 75 associated focused tests. No source revision changed.
  Remaining fixture defects were fixed without production edits: Wine paths
  now test pinned Y/Z home mapping, Undo Group proves the complete journal
  verification and its compact-output digest, and Harbor checks its actual
  per-field path ceiling with explicit short/long roots. The combined targeted
  rerun passed 17 tests. A new complete Non-live run remains required.
- Frozen `9256ae8` subsequently passed complete Non-live: **11954 passed,
  118 skipped, 27 deselected**, exit zero (809.03 s); fixed five-version
  Program: **5886 passed, 2 skipped**, exit zero (275.05 s). The two Program
  skips need native Windows. A rejected attempt to add `--basetemp` to the
  closed Program option surface ran no pytest; the next root used its canonical
  `-q -ra` options. Both completed gates left the frozen source clean and no
  owned test process. Wwise 2025.1.7 smoke passed with 4.41 s readiness and
  complete cleanup. Exact logs/digests are in the development-gate summary.
- The first prepared Luna-high pilot launcher ran once but blocked in native
  file-open before creating its campaign root. Computer-use inventory reported
  the Mac locked and unable to unlock automatically. No Agent or Wwise case
  started. The job was unloaded, PID 56126 exited, and its stack/diagnostic
  files remain under `expansion-pilot-launchers-9256ae8-r1`. The user has been
  asked to unlock; use a new launcher/root once startup prerequisites are
  resolved. This is not a model failure or semantic attempt.

The remaining sections retain the earlier pause checkpoint as historical context.
The two review defects listed below are repaired by the resume update; the
recorded real failures remain failures until new frozen attempts prove otherwise.

## Workspace and evidence

Main workspace: `/Users/xiye/Documents/Git/waapi-skills`, branch `main`, latest commit `353ba1f`.
Managed test worktree: `/Users/xiye/.codex/worktrees/music-capability-probes/waapi-skills`, last frozen candidate `bb710ff`.
Preserve its ignored evidence and quarantined failed sandboxes; do not archive/delete it without preserving that data.
All current uncommitted implementation changes remain in place. Unrelated user research drafts were not staged.

## Committed milestones

- `70298fa`: public create conflict/owner coverage.
- `cc240a0`: #123 explicit unsupported direct Action-creation boundary, existing Action edits retained; #110 input coverage.
- `3781167`: music capability investigation and bounded read probes.
- `6601ab1`: existing music scalar maintenance probes.
- `4231c52`: #124 exact-GUID binding of the evidenced MusicTransition display identity.
- `bb710ff`: seven business adapters, independent oracles, isolated real fixture preflight; exploratory probes moved under maintenance.
- `353ba1f`: reviewed interface inventory regenerated for the Action boundary.

## Actual validation, not inferred acceptance

- 2025 music public-read probes: 11 passed. 2022: 7 passed, 4 failed at documented capability boundaries.
- Scoped existing Transition property maintenance passed on both 2022 and 2025 after #124. This is not full Transition/fade acceptance.
- A 2022 existing Playlist loop scalar edit passed. The 2025 finite-loop/dependency attempt remains a documented unsuccessful probe, not business PASS.
- Program at `4231c52`: 5814 passed, 2 skipped, 1 inventory-digest failure. The regenerated-inventory test subsequently passed; the whole Program gate has not been rerun on the final implementation.
- Seven-adapter focused tests: 113 passed before subsequent small repair/archive-parameter edits.
- Real 2025 preflight at `bb710ff`: all seven cases failed; no Agent was launched. Original results remain failures.
- CLI/profile/legacy campaign focused regression: 256 passed (author report).
- Broker/runtime/timing focused regression: 80 passed (author report).
- Latest subprocess/preflight helper focused regression: 13 passed. Nonlive collection of destructive preflight is intentionally skipped by existing guards; it is not real execution evidence.
- Latest archive focused regression: 17 passed after three red regressions for missing post-state and hash-only confirmation.
- No new-profile Fresh pilot or final business acceptance has run. GitHub tickets in this expansion remain OPEN.

## Current uncommitted repairs

Luna max completed preflight Gateway subprocess isolation and bounded failed-case receipt capture. Same-process Gateway clients plus the trusted actor had caused txaio event-loop conflicts. The formal runtime author independently switched fixture Gateway calls to packaged subprocesses.

Existing test WAV filenames were misleading: all 15 files in the 2025 fixture shared one content hash; the entire repository test tree contained only two distinct WAV hashes. The helper now reuses existing assets and generates only the minimum distinct PCM shortfall inside an owned copy, as permitted by the user.

Sol high fixed archive PASS replay so independent before/after snapshots are required and assertions recomputed; confirmation requires the exact later-turn confirmation token rather than an artifact-hash substitute.

All seven cases now carry serializable expected oracle and preview parameters for immutable archive replay. Preserve these fields when resuming.

## Outstanding work

1. Resolve the confirmed runtime-review finding: `expansion_preview_notice` in `codex_task_runner_v3.py` accepts any nonempty post-Preview message (e.g. generic progress). It must establish a reviewable expected-effect notice without imposing brittle wording. Review not completed for every dynamic Broker receipt path.
2. Review and commit the current combined harness/profile/archive/preflight changes. Complete any remaining focused regressions; do not claim author-reported tests are live evidence.
3. Run frozen real preflight with a NEW explicit persistent `--basetemp` and JUnit/log outputs. Default pytest retention lost some detailed diagnostics during concurrent focused tests. Never reuse a basetemp path, since pytest deletes it.
4. Diagnose remaining real case failures from durable evidence: C06 sibling-RTPC setup verification, C08/C09/M01 setup/oracle behavior, and M05 missing native timing/configuration fields/types. Preserve strict outcome invariants; do not remove checks merely to pass.
5. Recheck 2022 and 2025 sequentially, using full pass → consolidated repair → failed-only rerun → final full pass. Keep source guards and cleanup evidence.
6. Run required final Program and Nonlive gates from a stable candidate, then the model pilot: gpt-6-luna high vs gpt-6-sol medium on 2025 C01/M01/C06 (six Fresh tasks, same default service tier); consider Luna medium only after Luna high succeeds reliably.
7. Final profile has 13 positive Agent units plus an independently observed M05/2022 capability boundary. No Agent/business PASS credit for that boundary. Final full acceptance and identical verify-only remain outstanding.
8. Finish music investigation dispositions and truthful documentation/ticket updates; do not equate scalar probes with full Playlist/Transition/Music Switch authoring coverage.

## Cost preferences for resumed work

The current coordinator is GPT-6.1 Sol high. Prefer GPT-6 Luna max for normal
implementation, fixture repairs, and evidence handling; use GPT-6.1 Sol medium
for cross-module work and reviews. The user does not want routine permission
questions. Do not reactivate completed Astra subagents for new implementation work.
