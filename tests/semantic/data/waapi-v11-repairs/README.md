# v1.1 repair first batch

Preparation profile: `waapi_v11_repairs_4`. This is a new contract, not a rerun or
replacement of historical integration or expansion evidence. It uses the formal
campaign, matrix, ScenarioLifecycle, fresh task, authenticated Broker and sealed
archive machinery. Do not launch until the combined candidate is frozen and the
coordinator explicitly starts the approved first batch.

| Workflow | Runner fixture | Agent result | Policy | Turns | Transactions |
| --- | --- | --- | --- | --- | --- |
| F1 | Existing RoomVerb independent Effect | Property first page, next page, exact PreDelay detail; change PreDelay to 24 ms | allow_changes | 1 | 1 |
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
missing or ambiguous plugin, unknown units, absent range/default, or 24 outside
the native range blocks the fixture. There is no guessed fallback field or
value. The native preflight test uses an explicit new WAAPI_REPAIR_PREFLIGHT_ROOT
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
