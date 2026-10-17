# WAAPI v1.1 repairs: acceptance checkpoint

Implementation, review and scoped acceptance are complete. Ten approved actual
Fresh attempts provide cumulative business PASS for F1–F4 across separately
frozen candidates and roots. This is not a single-root or same-candidate four-case
PASS. Latest executed candidate: `62d19e1c5cdc97fde30b0a26c97caf5075c65194`, whose
product/harness matches `0b063181`; the intervening commit records evidence only.
PR #173 may move to ready for review; do not merge it automatically.

## Development and native evidence

| Gate / candidate | Result |
| --- | --- |
| Five-version Program / `e8ca72d3` | 6942 passed, 3 skipped; exit 0, 460.09 seconds |
| Full Non-live / `e8ca72d3` | 18009 passed, 127 skipped, 34 deselected; exit 0, 1270.59 seconds |
| Final routing disclosure / `963a9f5a`, merged `0b063181` | 987 passed, 11 Windows-only skipped; exit 0, 48.82 seconds; includes 15 five-version public disclosure cases |

The adjacent JSON preserves full-gate log hashes. Skips grant no PASS credit.
The packaged Skill stayed byte-identical through `55063fa8`. The final successor
changes four product files only for catalog/schema routing descriptions: new
GameParameter creation with range/default versus an existing parameter's range
edit. It changes no compiler, payload, dispatch or Fresh prompt. Its focused
results are not another full Program/Non-live run. Both generated inventory
checks pass; source/contract seals were refreshed without changing coverage
counts or classifications.

Native public Gateway component evidence:

- GameParameter creation with Min=-12, Max=36, InitialValue=7 passed all five
  versions on `90018ae0`, with exact identity readback.
- Attenuation dependency preparation/readback passed all five versions on
  `700a8477`, plus 2025.1 false-routing setup on `813c993f`. See
  [native acceptance](../../tests/ATTENUATION_NATIVE_ACCEPTANCE.md).
- Independent ShareSet creation passed 2022.1–2025.1 on `df8e0610`. The 2021.1
  packaged boundary is explicit. A rejected classic-create encoding is not
  universal native impossibility; see [investigation](shareset-2021-classic-create-feasibility.md).
- Four formal 2025.1 fixture preparations passed on `c6119274` without Codex.
  All used owned sandboxes and preserved source hash/mtime.

These are separately identified component candidates, not a single all-version
live campaign. No native-Windows acceptance is claimed.

## Fresh results

All actual runs used Mac Wwise 2025.1, Terra / medium / default. The original
four-attempt budget received explicit additions of one, two, two, and one attempts.
Exactly ten Agent attempts have been consumed; none remain authorized.

| Root suffix / candidate | Attempts | Business outcome | Original verdict |
| --- | ---: | --- | --- |
| `first4-r1` / `e8ca72d3` | 0 | Startup guard stopped before Agent/Wwise | Campaign BLOCKED |
| `first4-r2` / `063eb519` | F1 | Broker rejected legitimate unchanged browse revision; no Agent write | Task FAIL; campaign BLOCKED |
| `first4-r3` / `80b653c0` | F1 | **Business PASS**: only PreDelay 25→24; all material checks pass | Task/matrix unit PASS; campaign BLOCKED on archive field contract |
| `remaining3-r4` / `459455b2` | F2 | Harness supplied wrong task reference; no project query/write | Task FAIL; campaign BLOCKED |
| `remaining2-r5` / `4b64ae3c` | F3 | Existing-object setRange selected for creation; no Draft/Preview/write | Task FAIL; campaign BLOCKED on missing legacy rejection proof |
| `final-f4-r6` / `2a2d8a20` | F4 | **Business PASS**: one independent RoomVerb Effect, exact parent/name/class, owner null | Selected 1/1 task/matrix/campaign PASS; identical verify-only |
| `retry-f2-f3-r7` / `cb50f129` | F2 | Legal offline `--version 2025.1 query-schema` misclassified by harness; zero Gateway dispatch | Task FAIL; campaign BLOCKED; F3 unattempted |
| `final-f3-r8` / `55063fa8` | F3 | Repeated existing-object setRange selection for new-object task; no Agent write | Task/matrix/campaign FAIL |
| `retry-f2-f3-r9` / `0b063181` | F2, F3 | F2 incomplete; **F3 Business PASS** | Selected 1/2; F2 FAIL, F3 PASS; campaign FAIL |
| `final-f2-r10` / `62d19e1c` | F2 | **Business PASS**: exact miss, unique fallback, exact-ID range/default readback; no change | Selected 1/1 task/matrix/campaign PASS; identical verify-only |

Every root name above has prefix `imac-v11-repairs-` beneath the local
`skills/waapi-skill-workspace/`. Raw failures were neither replayed nor regraded.
Only originally all-PASS roots received identical verify-only: r6 exited 0 with
all 78 inventoried files unchanged; r10 exited 0 with all 75 files unchanged.
The mixed r9 root was not replayed.

### Historical r9 F2: partial outcome, full case FAIL

The Agent read query-schema, queried the absent `Repair_WindSpeed`, received
explicit read-refinement permission, and independently found the unique
`Repair_WindVelocity` without asking for new approval. It then invented
`metadata list --object <GUID>`, which the public parser does not accept. The
requested Min/Max/InitialValue were never read. The final answer truthfully
reported the found identity and missing values; no project changes occurred.

Thus autonomous refinement is observed, but the complete F2 business obligation
is not met. The independent fixture's values do not substitute for Agent-visible
reads. The public query reference/schema disclose custom field projection through
`--include-field`; this attempt does not demonstrate a new business implementation
fault. It remains an ordinary FAIL, not a framework-only business PASS.

### Final r10 F2: complete autonomous read workflow

On the unchanged product/harness, the approved final F2 attempt read the
version-pinned query schema, obtained an exact no-match for Repair_WindSpeed,
then found unique Repair_WindVelocity without requesting new permission. It
used that exact GUID for field projection, refined non-unique field meanings,
and read Min=-12, Max=36 and InitialValue=7. The final answer reports the exact
identity, path and values. All eight independent assertions and all material
turn gates passed; before/after snapshots are identical. There was no Agent
project write, the source hash/mtime remained unchanged, and the PASS sandbox
was removed. Identical verify-only started neither Codex nor Wwise.

### Latest F3: independently verified creation

The Agent selected object.create, discovered the type and fields, refined its
field meanings when needed, produced one immutable Preview, gave concrete notice,
then executed and verified one transaction. Independent snapshots show exactly
one new GameParameter `Repair_WindRange`, Min=-12, Max=36, InitialValue=7, at
`\Game Parameters\Default Work Unit\Repair_WindRange`. All prior objects and
media remain identical; Preview before/after snapshots match. All seven business
assertions and material turn gates passed. The final answer matches that evidence.
This is F3 PASS on r9's exact candidate, not a four-case or single-root full PASS.

F1's separate assessment preserves its raw archive BLOCKED verdict. F1/F4 notice
and final-answer reviews found no material discrepancy. F1 reports native range
0–1000, default 25 and undisclosed units without inventing milliseconds.

## Repairs and proportional validation

Framework repairs covered startup profile admission, Draft revision semantics,
metadata receipt scope/argv spelling, connection-configuration archives, correct
read-only reference scheduling, failed assertion recomputation, and authenticated
zero-dispatch refusal evidence. Explicit remaining-work selectors never grant
run authorization. Old unmarked failures stay BLOCKED.

The r7 repair uses the Gateway parser for accepted command classification while
preserving raw argv and exact authentication hashes. It also fixes the exact
lexical interpreter identity in test-produced plans. The latter was a pure-test
finding, not an observed Fresh failure. Marked wrong/live-version refusals remain
FAIL and permit later units only with intact zero-dispatch proof; unmarked or
tampered evidence stops. Focused regression passed 596 tests, four additional
negative controls, and 231 follow-up tests; overlapping selections are not summed.
The review's P2 on refused-prefix interpretation was fixed and re-reviewed.

Two F3 failures motivated the final structured routing disclosure; its 987-test
regression and independent review passed, followed by r9 F3 PASS. See
[review closeout](waapi-v11-repairs-review-2026-10-17.md). Earlier framework focused
counts remain in preserved summaries and Git history, not a combined full gate.

## Protection, usage, audit and closure

Every actual attempt preserved source-project full hash and project mtime.
Passing sandboxes were removed, failed sandboxes quarantined, and scoped Wwise
processes cleared. One-shot LaunchAgents for r7/r8/r9/r10 were removed. Total recorded
usage: 2473976 input tokens, 2188288 cached input tokens, 19433 output tokens,
487.0698 Agent seconds. These are usage fields, not monetary estimates; fixture
and development-test work is separate.

The branch audit retains 849 routes, 24310 structural occurrences and explicit
unknown business mappings; structural consistency is not complete business
coverage. See [audit](../branch-coverage-audit.md). All twelve completed managed
worktrees were archived after verified evidence preservation. Immutable original
relocation records and separate supplements live under
`.waapi-skill-state/repair-evidence/`; the final supplement preserves five files
(9898 bytes), including captured result summaries rather than full stdout.
Original Fresh roots remain in the main workspace.

All four requested Fresh business workflows now have cumulative PASS evidence.
Historical failures, candidate differences, F1's raw archive BLOCKED verdict and
the audit's unknown business mappings remain explicit. This does not establish
all-branch functional support or native-Windows acceptance. Tickets #163–#172
are linked through PR #173's closing references; they close through the normal
merge workflow. This task prepares the reviewed PR and does not merge main.
