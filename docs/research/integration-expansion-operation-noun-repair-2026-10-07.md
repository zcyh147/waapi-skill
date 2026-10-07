# Operation-noun and owner propagation repair — 2026-10-07

The focused developer selection passed **2728 tests, zero failures and zero
skips in 5.28 seconds**: all 2657 previously retained notice controls plus 71
new controls. This is component evidence for [#147](https://github.com/zcyh147/waapi-skill/issues/147),
not Fresh Agent acceptance or issue closure. Independent review and subsequent
coordinator-owned gates remain required.

## Frozen source and causal RED

The latest `700914d` EXP25-C09 campaign remains a frozen
`visible_preview_notice` FAIL. Its six independent business assertions and
Gateway verification passed. This work copied raw event 23 and sealed
before-state/Preview data into standalone fixtures; it did not replay, regrade,
resume, verify or mutate that campaign.

The exact existing `_grammatical_notice` seam first reproduced an assertion
failure. An initial fixture-envelope extraction error produced a KeyError;
that log is retained and receives no semantic RED credit. After correcting
only the copied envelope, the exact witness failed for its intended reason.

Instrumentation at the existing seam proved both predicted causes:

- Nominal `此次追加已取得…授权` was counted as an extra append, with no Effect
  kind or approved name. Baseline bookkeeping was already supported.
- Changing only `此次追加` to `此次变更` exposed the independent owner failure:
  the authorization clause consumed the inheritance window, leaving the
  concrete `即将追加…` unanchored.

An independent designer froze 30 vectors before implementation: eight accepts
and 22 rejects. The copied bytes retain SHA-256
`c8c668d22c038813fa0996d8ca30fcab2e30553ef0f165d77238c6dfc274da8a`.
The first matrix run produced nine failures (the exact witness plus all eight
positives) and 22 passes. No frozen expectation was changed.

## Bounded correction

The shared language module receives the adapter's existing closed operation
action family from independently validated immutable context. That family
extends current-operation nouns consistently across authorization, Preview and
pending status, execution summaries and refusals. Notice prose does not grant
permission, map display labels to native classes or establish the concrete edit.
The separate durable `policy_checkpoint` authority remains unchanged.

Complete local clauses retain their original spans. A singleton attested owner
passes through validated neutral authorization, status and read components to
the next substantive clause. Unknown text stops that relation. Explicit owner,
field, value and polarity spans remain available to normal validation. Baseline
prose remains optional. Validated clause-edge spaces and tabs do not consume the
owner; unknown trailing text remains substantive.

The final controls reject explicit foreign/compound owners, wrong or denied
policy, uncertain/refused/missing edits, changed names/notes, hidden field
writes, incompatible native context and phase/provenance failures. Prior
curve count, units, point order, value and preservation controls remain intact.

## Additional-action distinction

Exploratory controls initially treated `另外` and bare `再` as proof of a second
append. The retained suite already has an explicit positive for the same
descriptor introduced with `另外`; root review also established that `之后再`
can sequence the same plan. Those exploratory expectations were corrected and
their original FAIL logs preserved. This was a clarification, not a repaired
failing requirement. Old assertions and the frozen 30 vectors were unchanged.

The narrow guard rejects a locally explicit second occurrence (`第二次` or
`第2次`) or paired repeat/count (`再…一次`) only after a concrete plugin plan
has already been proven. Restatement, discourse coordination, staged-plan
adoption and authorization/execution nouns remain compatible. With that guard
absent, the second-ordinal control reproduced RED; the paired repeat/count was
already rejected by existing grammar. Positive contrasts prove exact-descriptor
restatement, `另外`, `之后再` and the first append after a neutral read.

## Validation and limits

All runs used `ci/test.sh --mode nonlive` with explicit focused paths and the
attested Poetry developer interpreter. The exact previous 20-module selection
(original 19 plus coordinated attestation) was recovered from its prior log and
retained without modification. New controls exercise five operation-noun
alternatives, neutral component permutations and separators, clause-edge
whitespace, owner-window reset and the additional-action distinction.

The final log, JUnit, exact argv, exit code and all RED/intermediate/GREEN logs
are outside the disposable worktree under
`/Users/xiye/Documents/Git/waapi-skills/.waapi-skill-state/evidence/waapi-test-remediation/expansion-operation-noun-700914d-20261007`.
The accompanying [JSON report](integration-expansion-operation-noun-repair-2026-10-07.json)
records their hashes and intermediate failures, including the initial
overbroad coordinator guard and the clause-edge whitespace repair.

The branch began at integration `9f17623`; merging the integration tip before
handoff was already up to date. Supported `git lfs checkout` materialized the
exact locally pinned payloads, with no tracked dirt before scoped changes.
Ignored state was preserved. No full Program, full Non-live, Fresh, live Wwise
or native-Windows lane ran. The packaged Skill, runtime, prompt, suite, business
oracle, model judge and historical campaign evidence remain unchanged.
