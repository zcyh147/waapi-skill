# Implementation checkpoint — resumed

Date: 2026-09-28. Parent issue #108; implementation tasks #109–#122, repairs #123/#124.
The user requested a quota pause on 2026-09-28 and explicitly resumed implementation
on 2026-10-01. The implementation Goal is active; approved real preflight, model
pilot, and acceptance may proceed after their prerequisite gates.

## Resume update — 2026-10-01

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
  readback gaps. Their expansion-only repair is in progress separately; no
  timeout, infrastructure block, or uncertain execution may be promoted to PASS.
- Tickets #109, #110, #123, and #124 are closed from their scoped evidence;
  business and final acceptance tickets remain open.

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
