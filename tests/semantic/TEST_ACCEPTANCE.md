# Business acceptance and bounded test work

Current operating policy, approved 2026-10-10. Read this before planning a Fresh
batch, classifying a failure, changing a grader, or deciding what to rerun.
It governs future test coordination and acceptance reports, including Windows
impact assessment. Historical results retain their original contracts.

## 1. Judge the outcome, then classify the discrepancy

Report three separate facts for each unit: independent business checks, material
interaction/safety checks, and the original automated verdict. A Gateway success
string or the executing Agent's answer alone does not prove the outcome.

| Evidence | Acceptance and next action |
| --- | --- |
| Requested Wwise state and preservation are independently proven; authorization and other material checks pass | Business PASS. |
| The above holds; only minor wording, harmless presentation order, or missing reviewer context remains | Business PASS with a framework/wording note. Explain the discrepancy with the raw verdict; it does not alone require another Fresh run. |
| Wrong targets/values, extra changes, missing authorization, materially misleading completion/proof claims, or abusive responses | Material failure; diagnose the responsible layer. |
| Execution never happened, the result is unknown, or source protection/evidence integrity/cleanup cannot be established | BLOCKED or INDETERMINATE as applicable; no business PASS credit. |

Judge wording by its effect on the user's understanding and decisions. An
unsupported expression in a parser is not itself a demonstrated false claim.
Actual outcome evidence cannot manufacture prior consent or a missing material
Preview. Uncertainty about authorization, edit scope or actual results remains
blocking; uncertainty about a nonessential phrase does not.

Keep raw FAILs, reviewer uncertainty, archives and quarantines unchanged. Record
an evidence-backed acceptance assessment alongside them, citing the failed gate
and why it is nonmaterial. This policy does not change versioned grader code,
rubrics or machine PASS flags. Replay only an originally all-PASS root with
identical `--resume --verify-only`; a business assessment does not authorize
regrading or replaying a failed root.

## 2. Check evidence access before changing the judgment

For an apparent notice failure, compare the exact Agent-visible receipt with
the reviewer's supplied context first. Check missing reads, authorization facts,
type/field discoveries, scope, partial results and metadata freshness. Use the
existing authenticated evidence; missing reviewer context is not proof that the
Agent invented a fact. Give the reviewer only the appropriate pre-execution
facts, preserving identities, bounds and provenance.

Once a failure family repeats, resolve its attribution before another model
attempt. Increasing reasoning effort, editing wording rules or requesting more
votes on the same sealed notice is not a substitute for that diagnosis.

## 3. Prove the affected chain and rerun proportionally

Use the existing focused tests and `notice-fast` command during repair. For
changed evidence plumbing, exercise the actual producer, Broker/consumer,
judgment input and archive/verify-only path together, with a meaningful negative
control. Include valid producer normalization and admitted preparation recovery
where affected. Fake reviewer output proves transport, not language accuracy.

Finish a frozen batch before repairing ordinary failures. Stop for systemic
source, evidence, authorization or cleanup faults that make further runs unsafe
or uninterpretable. Consolidate confirmed repairs, then test the failed and
directly affected units in fresh roots. Change no code or options mid-batch.

At promotion, run the required development gate once on the combined change.
Choose additional Fresh coverage by what the change could invalidate. A new
commit or a local grader repair alone does not require another full matrix.
Run the full selection when shared execution/oracle changes invalidate its
earlier evidence or when an explicit acceptance requirement calls for it.
Label different-candidate, cumulative and targeted evidence accurately.

## 4. Keep completion and handoff small

Before the first batch, identify the required result, stopping conditions and
evidence. At closeout, report any newly found specification gap and its effect;
obtain a scope decision before turning it into substantial new work. Keep
optional telemetry, broader capabilities and documentation cleanup separate
from a proven business outcome. A deferred item is not a delivered feature.

Keep current decisions here and in a short task checkpoint; consult historical
logs only for the relevant failure family. Pass subagents scoped goals and file
pointers, with explicit `fork_turns="none"` recursively. During waits, follow
the known process/job and report milestones rather than launching new analysis
or repeating broad source reads. Prefer existing checks to more prose rules.

## Requested Windows impact assessment

Start with the existing [Windows prerequisites](../AGENTS.md#native-windows-fresh-agent-isolation)
and [new-root preflight](HARNESS_PITFALLS.md#new-root-preflight). Native shell/JSON
transport, UTF-8, user-profile isolation, interactive desktop ownership, locks
and cleanup need Windows evidence; Wine results alone do not establish them.

Run one complete native-Windows Non-live collection, then the existing expansion
selection: 13 positive Fresh units across 2022.1/2025.1 and the separate EXP22-M05
boundary. Use the macOS-tested executor/reviewer configuration for comparison;
avoid adding a model pilot or five-version real matrix to this first assessment.
Complete Non-live includes the fixed Program test nodes, so do not duplicate
that work solely for impact screening; report skipped Windows prerequisites
and failed checks explicitly. An explicitly required standalone Program release
gate remains a separate obligation.

Collect results before repairing ordinary failures. If a program failure
undermines safe execution or trustworthy observation, resolve that prerequisite
before the affected Fresh work; do not spend 13 attempts on the same broken
launcher. Otherwise retain the failure in the impact report and classify the
batch using the table above. Fix a demonstrated framework defect proportionally;
rerun only where fresh evidence is needed. Keep immutable profiles and raw
verdicts intact, and do not claim complete Windows acceptance for pending units.

## Retrospective basis

The [macOS completion record](../../docs/research/integration-expansion-acceptance-2026-10-09.md)
shows why these rules exist: the full baseline completed all 13 business outcomes,
while its overall result retained one notice-only FAIL. Supplying omitted Draft
discovery evidence then passed a targeted C09 and identical audit. Producer
normalization and valid failed-discovery/refinement histories also needed
regressions. Late phase-timing work was deferred. These observations support
earlier attribution and smaller repairs, not weaker business or safety checks.
