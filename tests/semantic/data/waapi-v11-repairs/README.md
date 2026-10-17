# v1.1 repair first batch

Preparation profile: `waapi_v11_repairs_4`. This is a new contract, not a rerun or
replacement of historical integration or expansion evidence. It uses the formal
campaign, matrix, ScenarioLifecycle, fresh task, authenticated Broker and sealed
archive machinery. Do not launch until the combined candidate is frozen and the
coordinator explicitly starts the approved first batch.

| Workflow | Runner fixture | Agent result | Policy | Turns | Transactions |
| --- | --- | --- | --- | --- | --- |
| F1 | Existing RoomVerb independent Effect | Property first page, next page, exact PreDelay detail; change PreDelay to numeric 24 | allow_changes | 1 | 1 |
| F2 | GameParameter Repair_WindVelocity, range -12..36, default 7 | Miss outdated Repair_WindSpeed spelling, refine to unique target, report values | read_only | 1 | 0 |
| F3 | Existing Game Parameters WorkUnit | New Repair_WindRange, range -12..36, default 7 | allow_changes | 1 | 1 |
| F4 | Existing Effects WorkUnit | New independent RoomVerb ShareSet Repair_Independent_Room | allow_changes | 1 | 1 |

Mac first batch, nominal Wwise 2025.1: four fresh CLI tasks, four user turns, four
executor CLI runs, three Agent transactions, no model reviewer calls.
The machine scheduler `model_calls` count denotes executor CLI runs, not API requests. Internal model
and tool iterations can involve multiple API requests; actual token usage comes
from the sealed campaign evidence. Executor is gpt-5.6-terra, medium reasoning,
default service tier. Each task has
600 cumulative Agent seconds and at most 96 Gateway calls; the batch has at most
2400 Agent seconds. No automatic retry or version multiplication. The only
smaller selections are the explicitly documented F2–F4 and F3–F4 continuations below.
Fixture setup calls and native preflight are deterministic runner work and are
recorded separately from Agent transactions. No Windows acceptance is claimed.

F1 must first attest the live RoomVerb class and exact PreDelay metadata. A
missing or ambiguous plugin, malformed unit availability, absent range/default, or 24 outside
the native range blocks the fixture. There is no guessed fallback field or
value. Unknown units remain explicitly unknown; numeric 24 does not imply milliseconds. The native preflight test uses an explicit new WAAPI_REPAIR_PREFLIGHT_ROOT
and the existing private-HOME/effective-Wine-prefix ScenarioLifecycle. It starts
no Agent and makes no project changes. All four task fixtures use the same
owned lifecycle and explicit external Gateway configuration. They never use a
user's project or infer endpoint settings from the Agent environment.

Each mutation requires the current immutable Preview, a durable policy
authorization, one execution reservation, Gateway verification, and independent
native readback. Preview admission rejects extra native writes or wrong targets.
The state oracle compares the complete bounded parent child set, target values,
source-project full hash/mtime and original media hashes. F1 additionally compares
all reflected plugin fields. F2 admits only bounded reads and requires an ordered
complete no-match followed by a unique target result with its exact name, type
and path. Authenticated target receipts must also expose Min, Max and InitialValue
with the expected values, either in that result or in bounded subsequent exact-ID
projections of the same GUID. Runner snapshots do not satisfy this Agent-visible
read obligation. Its independent snapshot must remain unchanged. F3 verifies the requested final values independently of the Agent's
wording. The first batch uses the new same-call creation implementation and its
one-transaction budget; a required staged fallback is a blocked prerequisite,
not authorization to spend another transaction or turn.

The new deterministic notice gate requires the target and concrete effect values after
Preview and before Execute, or an explicit reference to an earlier concrete plan.
It checks interaction order and effect evidence; it is not a language accuracy
reviewer. Preserve raw automated verdicts. Report independent state,
authorization/isolation, and any material final-answer or notice discrepancies
separately under TEST_ACCEPTANCE.md; do not relabel failed historical evidence.

Ordinary task failures are retained while the frozen batch continues only when
source integrity, authenticated evidence and cleanup remain proved. Uncertain
writes or cleanup failures stop the batch. Never replay the original write.
Any rerun, additional task, model change, or extra transaction needs a separate
scope decision. Three-policy recovery is covered by the focused Program suite;
F2 spends only the one approved read-only Fresh task.

## Preparation evidence and selection incident

On macOS candidate `ad8c2413`, the exact selected native preflight returned
RoomVerb PreDelay `Real32`, default 25, native range 0..1000 and UI range 0..200.
The UI data meaning was `None`; Gateway correctly returned unit availability
`unknown`. The original preflight failed its incorrect milliseconds assumption
(1 failed, 32 deselected). That root stays frozen as FAIL; the successor profile
requests numeric 24 and reports undisclosed units without inventing them.
The root is `skills/waapi-skill-workspace/repair-predelay-ad8c2413-r1`.

An earlier invocation accidentally omitted `-k`; destructive mode prepended its
five standard version modules despite the explicit file path. Sandbox tests ran
before the requested preflight. The owned driver group 65934 was interrupted
(exit 130). Its remaining proven-owned wrapper group 66835 and detached Wwise
PID 66850 were terminated with SIGTERM. No Agent ran. The subsequent scoped
process check found no Wwise process. This interrupted attempt earns no acceptance
credit; original failures, quarantines and the pending workflow sandbox remain.

The incident receipt is `.waapi-skill-state/evidence/repair-selection-incident.json`.
It references all three original category records, verifies their captured
source hashes against an independent recomputation, and records exact cleanup.
All 83 original source files (3,943,065 bytes) retain full SHA-256
`60855d800d1e95c7b8684d8c35f2fda247bc3c4d716f1375b6cded212c8c72bd`;
SampleProject mtime remains `1792176469219518550` ns. The WPROJ/WWU-only hash
and full tree metadata digest also match their captured before-state.
The source worktree for these ignored local artifacts is
`/Users/xiye/.codex/worktrees/waapi-repair-fresh/waapi-skills`.

The corrected exact-k preflight passed on `24859781`: 1 passed / 32 deselected,
three metadata pages and exact detail, zero project mutations and zero Agent
calls. Root `repair-predelay-24859781-r2` records lifecycle PASS, no errors,
unchanged full source hash/mtime and removed passing sandbox. The final process
check found no Wwise process. `metadata-preflight-2025.1.json` retains the exact
native metadata and source protection facts; it is not runtime authority.

After all merges, review and gates, the coordinator may start the approved
first batch from the repository root with this command (not run during preparation):

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py \
  --profile waapi_v11_repairs_4 --version 2025.1 \
  --model gpt-5.6-terra --reasoning-effort medium --service-tier default \
  --campaign-root skills/waapi-skill-workspace/imac-v11-repairs-first4-r1
```

The campaign root must be new. Do not append `--resume`, select extra cases, or
start a second batch under this preparation authorization.


## Authorized continuation after r3 F1

The original authorization covers F1–F4. Candidate `80b653c0`, root
`imac-v11-repairs-first4-r3`, completed F1's requested business result and all
material checks. Its campaign remains **BLOCKED** because the archive consumer
rejected the current `connection_configuration` field. The separate assessment
is retained at `.waapi-skill-state/repair-acceptance/r3-f1-business-assessment.json`.
That assessment does not rewrite the original root or grant a machine PASS.

A new frozen candidate may select exactly the ordered `REPAIR25-F2`,
`REPAIR25-F3`, `REPAIR25-F4` suffix through the same formal campaign. These are the
three unattempted workflows already authorized; F1 must not be repeated. This
selection has three fresh CLI tasks, three user turns, two Agent transactions,
1800 maximum cumulative Agent seconds (600 per task), no model reviewers and no
automatic retries. Arbitrary subsets, duplicates, reordered units, other versions
or changed model settings remain rejected. Omitting case IDs still selects all
four workflows. The profile JSON and historical roots remain unchanged.

After coordinator freeze, the continuation command is:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py \
  --profile waapi_v11_repairs_4 --version 2025.1 \
  --case-id REPAIR25-F2 --case-id REPAIR25-F3 --case-id REPAIR25-F4 \
  --model gpt-5.6-terra --reasoning-effort medium --service-tier default \
  --campaign-root skills/waapi-skill-workspace/imac-v11-repairs-remaining3-r4
```

Report this root's result as **three selected workflows**, separately from the
r3 F1 business assessment and its original BLOCKED campaign verdict. A 3/3 root
must never be described as a single-root or same-candidate 4/4 campaign PASS.

## Unattempted F3–F4 after r4

Root `imac-v11-repairs-remaining3-r4` attempted F2, which remains an ordinary
**FAIL**, with no business PASS. Its guessed query was rejected before project
query dispatch. The harness also wrongly required the operate reference for a
read-only task, and the archive consumer could not preserve the original
read-only notice gate; those framework discrepancies do not change the failed
read outcome. The original root and quarantine remain frozen.

Only F3 and F4 are still unattempted and already authorized. The formal campaign
additionally accepts exactly ordered `REPAIR25-F3`, `REPAIR25-F4`: two fresh CLI
tasks, two user turns, two transactions and 1200 maximum Agent seconds. This is
not authorization to retry F2 or F1. Default/all-four and the previously reviewed
F2–F4 selection remain unchanged for their documented purposes; arbitrary
subsets, repeats and permutations remain rejected.

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py \
  --profile waapi_v11_repairs_4 --version 2025.1 \
  --case-id REPAIR25-F3 --case-id REPAIR25-F4 \
  --model gpt-5.6-terra --reasoning-effort medium --service-tier default \
  --campaign-root skills/waapi-skill-workspace/imac-v11-repairs-remaining2-r5
```

A passing root would establish only its selected 2/2 result. F1's separate
business assessment and F2's original FAIL must remain visible in any overall
acceptance report. No failed root is regraded by this continuation.
