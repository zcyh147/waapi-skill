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

Mac first batch, nominal Wwise 2025.1: four fresh tasks, four user turns, four
executor model invocations, three Agent transactions, no model reviewer calls.
Executor is gpt-5.6-terra, medium reasoning, default service tier. Each task has
600 cumulative Agent seconds and at most 96 Gateway calls; the batch has at most
2400 Agent seconds. No automatic retry, case subset, or version multiplication.
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
complete no-match followed by a unique exact target result; its snapshot must be
unchanged. F3 verifies the requested final values independently of the Agent's
wording. The first batch uses the new same-call creation implementation and its
one-transaction budget; a required staged fallback is a blocked prerequisite,
not authorization to spend another transaction or turn.

The new deterministic notice gate checks that the Agent supplies text after
Preview and before Execute. It is an interaction-order check, not a language
accuracy reviewer. Preserve raw automated verdicts. Report independent state,
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
