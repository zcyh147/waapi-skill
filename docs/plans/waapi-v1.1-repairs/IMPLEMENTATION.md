# Implementation checkpoint

Updated 2026-10-17. Integration branch: `codex/waapi-v11-repairs`.
Review base: `f633403a`. Draft PR: https://github.com/zcyh147/waapi-skill/pull/173

## Scope and budget

Implementation and deterministic tests cover Wwise 2021.1–2025.1, with explicit
version boundaries. Tickets #164–#172 are in English under spec #163. The first
Fresh batch consists of four Mac workflows on 2025.1, once each; additional actual
Fresh tasks or reruns require user approval. No Windows real-host acceptance is
claimed. User projects, including Lyra, are outside the test scope.

## Implemented work

- #164: generated route/schema/business mapping audit, portable source identities,
  source seals, and explicit unknowns/backlog. Reflected availability is not
  functional coverage; additional audit findings do not silently expand this scope.
- #165: config-only live connections and persistent configuration/project/version
  binding across Drafts and transactions; stale or changed bindings fail closed.
- #166: property list, paging, exact detail and scoped selection; compact discovery
  retains metadata and actionable boundaries instead of silently truncating fields.
- #167: supported conditional dependencies, deduplication and conflict rejection;
  derived changes appear in Preview. Native attenuation tests passed on all five
  versions, with a further 2025.1 false-routing case.
- #168: same-call GameParameter creation with range/default. Public Gateway native
  tests passed on all five versions: Min=-12, Max=36, InitialValue=7, exact identity.
- #169: independent Effect ShareSet topology, distinct from an owner's effect slot.
  Public Gateway native tests passed on 2022.1–2025.1. The packaged 2021.1 boundary
  remains explicit. The source-guided classic create encoding was rejected by
  native Wwise; this is not proof that every conceivable native alternative fails.
- #170: receipt-based recovery within the existing three policies. Read-only
  diagnosis/refinement may continue; uncertain original writes are never replayed.
- #171: user projects and outputs are retained. Required paired resource cleanup
  remains; test sandbox disposal belongs only to the test lifecycle.
- #172: formal four-workflow Fresh profile, authenticated evidence, native oracles,
  notice checks and archive verification implemented. Actual Fresh acceptance is
  incomplete: all four workflows have now been attempted within the expanded
  nine-attempt approved budget. F1, F3 and F4 have business PASS; F2 remains incomplete.

## Completed validation

Frozen integration candidate `e8ca72d3710a94ea2067ad484ae7fdc74587e0d4`:

| Gate | Result |
| --- | --- |
| Five-version Program | 6942 passed, 3 skipped |
| Non-live | 18009 passed, 127 skipped, 34 deselected |

Skipped Windows/native or absent optional historical evidence is not passing
coverage. Logs and JSON receipts are preserved under
`.waapi-skill-state/repair-acceptance/e8ca72d3710a94ea2067ad484ae7fdc74587e0d4/`.

Independent Standards and Spec review findings were fixed and re-reviewed. The
latest startup repair also received a focused review with no actionable findings.
After merge `8047a630`, the ten relevant repair/expansion test modules passed
161 tests. The earlier full gates remain evidence for their exact candidate;
this focused successor result is not relabeled as a new full-gate run.

Native component evidence used the existing owned ScenarioLifecycle and private
HOME/effective Wine prefix. Passing runs proved unchanged source hashes/mtime,
removed their passing sandbox, and left no scoped Wwise processes. Failed probe
roots remain preserved. See the native acceptance and research reports for exact
candidate/version evidence; these are component tests, not Fresh acceptance.

## Fresh results and remaining decision

Nine approved actual attempts are complete. F1, F3 and F4 have independently
established business PASS on separately identified candidates. The latest
`0b063181` root passed F3 and failed F2 (selected 1/2); no failed root was replayed.
F2 autonomously refined a no-match query to the correct unique target but then
invented a metadata command and did not retrieve required range/default values.
That partial result is not full F2 PASS. All source projects remained unchanged.

The repeated F3 wrong-route selection led to a reviewed, guidance-only product
repair: distinguish new GameParameter creation with range/default from editing
an existing range. Five-version public disclosure and related regression passed
987 tests / 11 Windows-only skips; both inventory checks passed. The installed
Skill is byte-identical to the original full-gate candidate only through
`55063fa8`; final guidance-only successor evidence is separately identified.

See the [acceptance record](../../research/waapi-v11-repairs-acceptance-2026-10-17.md).
Further Fresh needs new approval, or the user may accept the remaining F2
limitation. Until that decision, keep PR #173 draft. Do not merge to main.

## Evidence retention

All twelve completed managed worktrees were archived after byte-verified copies.
Original and supplementary manifests under `.waapi-skill-state/repair-evidence/`
remain separate. The final supplement `supplement-query-routing-963a9f5a`
preserves five files (9898 bytes), including test-result summaries, not full stdout.
Failed/blocked campaign roots and their quarantines remain untouched.
