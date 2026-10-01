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
  M05 capability boundary. All 14 final source hash/mtime/tree-metadata guards
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
  `2732ac9` passed all seven nodes. All 14 full-preparation source full hashes,
  project mtimes, tree metadata, and scoped-process cleanup checks passed;
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
