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

### Test selection and evidence reuse (approved 2026-10-23)

The user reconfirmed representative functional testing on 2026-10-26.
Keep complete native-to-public parameter/option mapping against all five pinned
definitions. Aim for one or two representative public cases per meaningful
parameter branch or shared mechanism; remaining legal values stay selectable.
Simple APIs use an ordinary happy path and reusable relevant proof. Structural
mapping rows, enum values, optional-field permutations and collection sizes are
not individual execution or evidence-ID quotas.

Select real Wwise checks for actual business risk, independent behavior and
host/version differences. Reuse matching valid observations; preserve original
failed outcomes. CRUD, queries and compound changes retain appropriate identity,
policy, execute-once, outcome and cleanup checks. Unsupported normal-user
functions and missing required business proof remain unresolved. The completion
checker must distinguish complete option mapping from selected representative
evidence; necessary reconciliation is owned by #195, not a new per-leaf test
framework. Fresh remains under #194 with budget zero until separately approved;
#195 coordinates the required stable-candidate full Program/Non-live gates.

Select tests from the changed implementation and its callers. Group independent
cases into one affected run while retaining separate assertions, outcomes and
isolated mutable state. Share expensive setup only when it cannot leak state
between cases. Similar ticket titles or matching schema shapes alone do not
establish equivalent behavior or justify omitting a version.

For each implementation slice, record the requested business outcome, changed
shared mechanism, reusable evidence, selected test nodes and remaining version
differences. Parameterize common mechanisms over the five pinned definitions;
use targeted native cases for behavior that code tests or retained matching-host
evidence do not establish. One native workflow may support several obligations
only when its actual observations prove each one individually.

Build one public Gateway business flow end to end in code tests first, then
perform the necessary native validation. Extend the flow to new shapes and
version differences after its shared path works. Fresh separately tests Agent
discovery/use of that interface; it is not required for every code integration
test and still needs an explicitly approved case budget.

When expanding that flow, keep every new group connected to the ordinary
consumer and finalizer, including a missing-required-evidence control. Check
scope, dependency closure and metadata contracts before expensive producers.
Isolated development may use a frozen dependency that passed its focused tests;
integration and publication still require independent review.

For a new or changed native evidence collector, that code test must reach the
existing final report/category writer and its persisted result, not stop at the
collector's returned dictionary. Substitute the external Wwise execution while
exercising the real collector, outcome checks and finalizer. Cover successful
and failed outcomes, including retained partial evidence; exercise bounded
fallbacks when changed. Reuse this proof while those consumers remain unchanged.
Do not spend a native attempt discovering missing report fields or incompatible
producer/consumer shapes that this code test can establish.

Classify a failure before selecting reruns. Wrong Wwise state, changed unrelated
objects or missing material authorization require the affected business checks.
A report, directory, stale test expectation or inventory-accounting defect
requires focused checks of that producer/consumer chain. Reuse original native
observations when their relevant source, contracts and material evidence remain
valid; missing or ambiguous outcome evidence still requires targeted collection.
Preserve the original failed verdict and record the separate assessment. A new
commit or unrelated documentation edit alone does not invalidate native effects.

Before materially increasing verification depth, test cost or required runtime
behavior, present the current proof, remaining user-visible risk and proposed
extra work to the user for a decision. Keep the unresolved requirement assigned
to its existing parent while awaiting that decision. Do not silently remove it
or expand it into a stronger completion requirement. This applies to complete
waveform mathematical verification as well as other costly special cases.

Use the existing focused tests and `notice-fast` command during repair. For
changed evidence plumbing, exercise the actual producer, Broker/consumer,
judgment input and archive/verify-only path together, with a meaningful negative
control. Include valid producer normalization and admitted preparation recovery
where affected. Fake reviewer output proves transport, not language accuracy.

Finish a frozen batch before repairing ordinary failures. Stop for systemic
source, evidence, authorization or cleanup faults that make further runs unsafe
or uninterpretable. Consolidate confirmed repairs, then test the failed and
directly affected units in fresh roots. Change no code or options mid-batch.
During code repair, rerun the failed cases and callers affected by the fix;
retain unaffected passing results. A single failed case does not by itself
justify rerunning the whole Program, Non-live or native selection.
For an existing large test file, select the specific affected test nodes.
Sharing a file with an affected consumer does not justify rerunning every test
in that file; broader selection needs a shared behavior that the change affects.

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

## Windows and release follow-up (2026-10-10)

The release closeout adds four lessons without reopening completed acceptance:

- **Repeated command-copy failure needs a code-level response.** The decoded-copy
  prompt alone reproduced C08's doubled separators. Gateway-generated runner
  spelling then passed the affected native workflows with exact-copy checks
  intact. The [research and repair record](../../docs/research/windows-agent-command-escaping-2026-10-10.md)
  owns the evidence and limits; this is implemented, not a general promise that
  models always copy commands correctly.
- **Prove native transport before spending on Fresh cases.** UTF-8, argv length,
  PowerShell relay behavior and process cleanup need cheap native checks.
  [Portability repairs](../../docs/research/windows-expansion-portability-2026-10-10.md)
  and [bounded reviewer stdin](../../docs/research/windows-reviewer-stdin-2026-10-10.md)
  have focused regressions. Wine success alone is not native-Windows proof.
- **Use one remote execution owner.** SSH-controlled InteractiveToken/Limited
  Scheduled Tasks and durable result files worked without Desktop thread
  messaging. Ownership and scoped cleanup are documented in the stdin repair
  record; a new reusable orchestration service is not claimed or required.
- **Reconcile publication documents before tagging.** Compare the release diff
  with both READMEs, their Scope and validation links, the test inventory and
  release notes. Remove stale pending claims, distinguish runtime fixes from
  test-only work, and preserve raw verdicts, candidate boundaries and deferred
  work. Verify the install bundle against the merged commit and its uploaded
  checksum. This is a documented manual checklist, not an automated CI gate;
  completed release tags and assets remain unchanged by later documentation work.
