# WAAPI v1.1 repairs: acceptance checkpoint

Status: implementation and deterministic validation complete; the approved Fresh
batch has finished with two business passes and two incomplete workflows. Current
executed candidate: `2a2d8a20`. PR #173 remains draft pending the user’s acceptance decision.

## Completed development gates

Frozen candidate `e8ca72d3710a94ea2067ad484ae7fdc74587e0d4` passed:

| Gate | Passed | Skipped | Deselected | Seconds |
| --- | ---: | ---: | ---: | ---: |
| Fixed five-version Program | 6942 | 3 | — | 460.09 |
| Full Non-live | 18009 | 127 | 34 | 1270.59 |

Both commands exited 0 and left their candidate clean. The adjacent JSON record
contains log digests. Windows-only and live/optional-evidence skips grant no PASS
credit. These are the exact full-gate candidates, not a claim that every later
harness commit received another full run. Subsequent code changes are confined to
the test framework; the packaged Skill remains byte-identical to `e8ca72d3`.

The startup repair passed 161 focused tests. The subsequent Draft metadata
Broker/archive repair passed 767 focused tests with 6 native-Windows skips;
112 overlapping final checks passed. Review follow-up passed 66 affected tests.
Selections overlap and must not be added into one new total.

## Native component evidence

- Same-call public Gateway GameParameter creation passed 2021.1–2025.1 on
  `90018ae0`, independently checking Min=-12, Max=36, InitialValue=7 and identity.
- Attenuation dependency preparation/readback passed all five versions on
  `700a8477`, plus a 2025.1 false-routing setup on `813c993f`. See
  [the native acceptance record](../../tests/ATTENUATION_NATIVE_ACCEPTANCE.md).
- Independent ShareSet creation passed 2022.1–2025.1 on `df8e0610`. The 2021.1
  packaged boundary remains explicit. The rejected classic-create encoding is
  a scoped probe, not universal native impossibility; see
  [the source-backed investigation](shareset-2021-classic-create-feasibility.md).
- All four formal 2025.1 fixture preparations passed on `c6119274` without
  starting Codex. Their source hashes/mtime stayed unchanged and their sandboxes
  were removed. This grants no Fresh acceptance credit.

These component candidates are separately identified evidence, not a single
all-version live campaign. No native-Windows acceptance is claimed.

## Fresh attempts and business assessment

The user approved one F1 rerun together with the still-unattempted F2–F4.
Exactly five real Agent attempts have now been consumed across four unique
workflows. There were no Windows Fresh tasks or version multiplication.

| Root / candidate | Actual Agent attempts | Independent business assessment | Raw result |
| --- | ---: | --- | --- |
| `imac-v11-repairs-first4-r1` / `e8ca72d3` | 0 | No Agent or Wwise launch; sealed-digest parser guard rejected startup | Campaign BLOCKED |
| `imac-v11-repairs-first4-r2` / `063eb519` | 1, F1 | No Agent Preview/Execute; Draft browse revision rejected by Broker | Task FAIL; campaign BLOCKED |
| `imac-v11-repairs-first4-r3` / `80b653c0` | 1, F1 | **Business PASS**: only PreDelay 25→24, all other settings/objects/media/source unchanged; authorization and notice pass | Task/matrix unit PASS; campaign BLOCKED on stale archive field contract |
| `imac-v11-repairs-remaining3-r4` / `459455b2` | 1, F2 | **Not completed**: harness forced the operate reference for a read-only query, then the guessed query was rejected before dispatch | Task FAIL; campaign BLOCKED on rejected-read evidence |
| `imac-v11-repairs-remaining2-r5` / `4b64ae3c` | 1, F3 | **Not completed**: Agent selected existing-parameter `setRange` for new-object creation; Draft admission rejected before dispatch | Task FAIL; campaign BLOCKED because legacy refusal lacks structured proof |
| `imac-v11-repairs-final-f4-r6` / `2a2d8a20` | 1, F4 | **Business PASS**: exactly one independent RoomVerb Effect, class 7733251, correct parent/name, owner null; prior state preserved | Task/matrix/campaign PASS, selected **1/1**, plus identical verify-only |

F4 verify-only exited 0 and left all 78 inventoried campaign files byte-identical.
It started no Agent or Wwise. F1 has a separate evidence-backed business
assessment under TEST_ACCEPTANCE.md; its raw BLOCKED campaign was not replayed,
regraded, or relabeled. None of these roots is a single-root four-workflow PASS.
F2 and F3 have no successful Fresh business evidence.

Manual final-answer/notice review found no material discrepancy for F1 or F4.
F1 correctly reported native range 0–1000, default 25 and undisclosed units.
F4 correctly reported the independent ShareSet without a Sound/Bus attachment.
Both provided the required concrete notice before their one execution.

All five attempts retained source full hashes and project mtimes. Passing
sandboxes were removed, failed sandboxes quarantined, and no scoped Wwise
executable remained. The complete usage totals are 1342192 input tokens,
1194240 cached input tokens, 9690 output tokens and 202.2268 Agent seconds.
These are recorded usage fields, not a monetary estimate. Non-Agent fixture,
program-test and framework repair time is separate.

### Framework repairs after the first attempt

- Admit only the intended sealed repair child; preserve model/version/selection
  restrictions.
- Preserve Draft list/page revisions and incremented selection revisions; prove
  the actual Gateway producer through authenticated Broker, notice and archive.
- Validate the current Preview's closed connection configuration and its match
  to endpoint/version. Current repair records require the binding; legacy
  reading remains a separately closed variant.
- For current repair plans, seal and enforce the correct reference schedule:
  read-only uses query; mutations use operate. The historical F2 instructions
  were wrong and remain recorded as such. The installed Skill already gave the
  correct routing instruction; it was not changed to compensate for the harness.
- Preserve ordinary read-refusal FAILs with independently recomputed complete
  assertion maps. A future initial policy refusal has an authenticated closed
  zero-dispatch marker only before any Draft, transaction or execution
  reservation; incomplete proof, tampering and later-phase claims still stop.
  Old unmarked unknown refusals, including r5, remain BLOCKED.
- Permit only documented, explicit remaining-work selections. These enabled
  still-authorized F2–F4, F3–F4 and finally F4 without repeating earlier cases.
  Counts and budgets reflect the actual selection; they do not earn four-case
  acceptance credit.

These test-framework changes passed focused regressions and independent review.
Reported selections include 239 and 114 passes; 2153 and 119 passes; follow-up
171 and 22 passes; and 683 passes / 6 native-Windows skips with overlapping
178, 40 and 122 passing selections. They overlap and are not added into a new
aggregate. The packaged Skill remains byte-identical to the full-gate candidate.

### Remaining decision

The approved Agent budget is exhausted. F2 needs a fresh valid test after its
harness repair. F3 remains a genuine route-selection failure under its frozen
instructions; no missing native creation capability was demonstrated and no
product routing change was made solely to obtain a green retry. Additional F2
or F2–F3 attempts require a new user decision. The alternative is explicit
acceptance of delivery with these Fresh limitations. Until then, PR #173 stays
draft and full Fresh acceptance is not claimed.

## Audit, review and evidence retention

Both generated inventory checks passed. The branch audit retains 849 routes,
24310 structural occurrences and explicit unknown business mappings; structural
consistency does not establish complete business coverage. See
[the audit](../branch-coverage-audit.md) and
[review closeout](waapi-v11-repairs-review-2026-10-17.md).

The original ten completed managed worktrees were archived after evidence preservation.
A further framework-repair worktree is retained until its final evidence copy.
Original native evidence is indexed under `.waapi-skill-state/repair-evidence/`;
its first relocation manifest is immutable. Additional fixture and repair
records use separate supplementary manifests. Original Fresh roots remain in
the main workspace. Tickets #163–#172 are linked to draft PR #173; the PR is not
ready while the agreed Fresh acceptance remains incomplete.
