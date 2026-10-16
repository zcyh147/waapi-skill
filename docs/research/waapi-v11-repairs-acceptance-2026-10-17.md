# WAAPI v1.1 repairs: acceptance checkpoint

Status: implementation and deterministic validation complete; Fresh acceptance
incomplete. Integration repair candidate: `121ab54f`. PR #173 remains draft.

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

| Root / candidate | Actual Agent attempts | Independent outcome | Raw result |
| --- | ---: | --- | --- |
| `imac-v11-repairs-first4-r1` / `e8ca72d3` | 0 | No Agent or Wwise launch; matrix parser rejected the repair child | Campaign BLOCKED |
| `imac-v11-repairs-first4-r2` / `063eb519` | 1 (F1) | Property page 1 returned; no Agent Preview or Execute; requested change not completed | Task/matrix FAIL; campaign BLOCKED |

F2–F4 were not attempted. F1 spent 29.7508 Agent seconds, reporting 183892 input
tokens (160768 cached) and 2082 output tokens; these are recorded usage fields,
not a monetary estimate. Its source full hash and mtime remained unchanged. Its
failed sandbox is quarantined; no scoped Wwise executable remained. No business
PASS is claimed, and neither failed/blocked root was replayed or regraded.

The first defect was an expansion-only sealed-digest guard. The second was a
Broker assumption that listing properties increments Draft revision. Actual
Gateway transitions are start 1, bind 2, list 2, page 2, selection 3. Repairs now
exercise the real producer through authenticated Broker, notice and archive
checks, including scope/token/order and invalid-transition negatives. The new
F1 oracle also recognizes legitimate Draft list/page/selection. Review caught
and resolved equals-form option and exact-ID/path-scope handling.

The still-needed selection is F1 once more plus the three unattempted workflows,
all on Mac 2025.1 with Terra/medium/default. This adds one Agent attempt beyond
the original budget and is awaiting user approval. No further Fresh launch is
authorized by this checkpoint. Only an all-PASS root may receive identical
verify-only. A failed root stays frozen regardless of later repair results.

## Audit, review and evidence retention

Both generated inventory checks passed. The branch audit retains 849 routes,
24310 structural occurrences and explicit unknown business mappings; structural
consistency does not establish complete business coverage. See
[the audit](../branch-coverage-audit.md) and
[review closeout](waapi-v11-repairs-review-2026-10-17.md).

All ten completed managed worktrees have been archived after evidence preservation.
Original native evidence is indexed under `.waapi-skill-state/repair-evidence/`;
its first relocation manifest is immutable. Additional fixture and repair
records use separate supplementary manifests. Original Fresh roots remain in
the main workspace. Tickets #163–#172 are linked to draft PR #173; the PR is not
ready while the agreed Fresh acceptance remains incomplete.
