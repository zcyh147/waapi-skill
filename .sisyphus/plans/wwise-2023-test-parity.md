# Wwise 2023.1 Test Parity with 2022.1 Scale

## TL;DR
> **Summary**: Bring Wwise 2023.1 test coverage to the same evidence standard and scale as 2022.1 Phase 2/2.1 without reopening risky environment-sensitive API families. Every reflected 2023.1 API must be classified exactly once, and behavioral/live/destructive promotions require real 2023.1 evidence.
> **Deliverables**:
> - 2023.1 parity baseline/diff artifact against 2022.1 coverage.
> - Updated 2023.1 coverage, live matrix, Phase 2 summary, URI policy, wrapper-only/deferred resources.
> - Expanded 2023.1 live read-only and destructive sandbox tests with evidence artifacts.
> - Audit/unit/docs/eval tests proving no manifest-only overclaims, no default-version regression, and no unsafe mutation.
> - Review packet documenting promoted, deferred, excluded, and non-blocking Windows evidence.
> **Effort**: Large
> **Parallel**: YES - 4 waves
> **Critical Path**: Task 1 → Tasks 2-6 → Tasks 7-10 → Final Verification Wave

## Context
### Original Request
- User: "wwise 2023已经接入完成了，但我希望把test case做到2023跟2022规模一样"
- User: "需要新创建一个计划"
- User clarified: only 2023.1; do not include 2024/2025.
- User requested commits during execution.

### Interview Summary
- Parity scope: **Full 2022 Parity** — align 2023.1 with 2022 Phase 2/2.1 API-by-API classification, behavioral evidence, live/destructive coverage scale, and classify 2023-specific additions individually.
- Risky API families: keep profiler, transport, soundengine, UI, CLI, remote, debug deferred/excluded unless a safe existing read-only probe already exists; do not broadly reopen.
- Windows validation: non-blocking evidence/caveat only; macOS WwiseConsole is the primary completion gate.
- 2023.1 remains explicit opt-in; default behavior remains 2022.1.
- Live/destructive execution remains gated. Live requires `WWISE_VERSION=2023.1 WWISE_LIVE=1`; destructive additionally requires `WWISE_DESTRUCTIVE=1` and a sandbox root.

### Metis Review (gaps addressed)
- Source of truth: use committed 2022.1 coverage/deferred/live resources plus their audit tests as baseline; treat generated inventory/review packet as evidence, not as sole truth.
- Parity meaning: same evidence standard with reclassification allowed when 2023.1 behavior differs or 2023.1 adds/renames/removes APIs.
- Required classification: all 181 reflected 2023.1 APIs classified exactly once; no orphan APIs.
- Promotion rule: accepted calls alone never count as behavioral/live-tested; require readback, cleanup, artifact, or state-transition proof.
- Safety proof: destructive tests must fail closed and prove installed SampleProject plus `tests/_org/2023.1` remain immutable.
- Wrapper scope: do not add product wrappers merely to improve coverage. Wrapper work is out of scope unless a test-only harness is necessary and does not change runtime API behavior.

## Work Objectives
### Core Objective
Achieve 2023.1 test parity with the 2022.1 Phase 2/2.1 coverage scale by classifying every 2023.1 reflected API and adding/recording only evidence-backed behavioral/live/destructive coverage.

### Deliverables
- `.sisyphus/evidence/wwise-2023-test-parity/parity-baseline.json`
- `.sisyphus/evidence/wwise-2023-test-parity/parity-review-packet.md`
- Updated `resources/coverage/2023.1/api-coverage.json`
- Updated `resources/coverage/2023.1/live-coverage-matrix.json`
- Updated `resources/coverage/2023.1/phase2-coverage-summary.json`
- Updated `resources/coverage/2023.1/phase21-uri-policy.json`
- Updated `resources/coverage/2023.1/wrapper-only-category-policy.json` only if counts/rationales change
- Updated `resources/deferred/2023.1.json`
- Updated/added 2023.1 live/destructive tests under `tests/live/` and `tests/destructive/`
- Updated audit/unit/docs/eval tests under `tests/unit/`, `references/`, and `evals/` where claims change

### Definition of Done (verifiable conditions with commands)
- `python -m pytest -q` exits 0 with no WwiseConsole launch required and no 2023.1 live/destructive execution unless opt-in env vars are set.
- `WWISE_VERSION=2023.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" WWISE_LIVE=1 python -m pytest tests/live/test_2023_live_prerequisites.py tests/live/test_2023_reflection_inventory.py tests/live/test_2023_waql_live_matrix.py -q` exits 0 and writes live read-only evidence under `.sisyphus/evidence/wwise-2023-test-parity/` or the existing 2023 WAQL evidence root.
- `WWISE_VERSION=2023.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 python -m pytest tests/destructive/test_2023_project_mutation_sandbox.py tests/destructive/test_2023_soundbank_audio_sandbox.py tests/destructive/test_2023_switchcontainer_assignment_sandbox.py -q` exits 0 and proves source immutability.
- `python -m pytest tests/unit/test_2023_api_resource_coverage.py tests/unit/test_2023_live_coverage_matrix.py tests/unit/test_2023_deferred_registry.py tests/unit/test_2023_cross_version_audit.py tests/unit/test_2023_docs_contract.py -q` exits 0 and proves all 181 reflected APIs are classified exactly once.

### Must Have
- All 181 reflected 2023.1 APIs classified exactly once.
- Coverage summaries reconcile: status counts sum to 181; live/deferred/excluded/resource counts match across `api-coverage`, `live-coverage-matrix`, `phase2-coverage-summary`, `phase21-uri-policy`, and deferred registry.
- 2023.1 live/destructive tests must use exact installed paths:
  - `/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh`
  - `/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj`
- Destructive mutations must target only copied sandboxes under `WWISE_SANDBOX_ROOT`.

### Must NOT Have (guardrails, AI slop patterns, scope boundaries)
- MUST NOT claim behavioral/live-tested coverage from manifest reflection, schema presence, skipped tests, or accepted calls without assertions.
- MUST NOT mutate installed SampleProject or committed `tests/_org/2023.1`.
- MUST NOT make Windows validation a blocking gate.
- MUST NOT add 2024/2025 work.
- MUST NOT broadly reopen profiler, transport, soundengine, UI, CLI, remote, or debug.
- MUST NOT add product wrappers solely to satisfy coverage optics.
- MUST NOT remove 2022.1 as `DEFAULT_WWISE_VERSION`.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: tests-after with existing pytest framework; live/destructive execution remains explicit opt-in.
- QA policy: Every task has agent-executed scenarios.
- Evidence: `.sisyphus/evidence/task-{N}-{slug}.{ext}` plus `.sisyphus/evidence/wwise-2023-test-parity/*`.

## Execution Strategy
### Parallel Execution Waves
> Target: 5-8 tasks per wave. <3 per wave (except final) = under-splitting.
> Extract shared dependencies as Wave-1 tasks for max parallelism.

Wave 1: Task 1 baseline/diff source-of-truth.
Wave 2: Tasks 2-6 resource classification, live read-only expansion, destructive sandbox expansion, fail-closed safety, deferred/excluded policy.
Wave 3: Tasks 7-10 audits/docs/review packet/default-version regression/evidence reconciliation.
Wave 4: Final Verification Wave F1-F4.

### Dependency Matrix (full, all tasks)
- Task 1 blocks Tasks 2, 5, 7, 8, 10.
- Task 2 blocks Tasks 7, 8, 10.
- Task 3 blocks Tasks 7, 8, 10.
- Task 4 blocks Tasks 6, 7, 8, 10.
- Task 5 blocks Tasks 7, 8, 10.
- Task 6 blocks Tasks 7, 8, 10.
- Tasks 7-10 block F1-F4.

### Agent Dispatch Summary (wave → task count → categories)
- Wave 1 → 1 task → deep.
- Wave 2 → 5 tasks → deep, unspecified-high.
- Wave 3 → 4 tasks → unspecified-high, writing, quick.
- Wave 4 → 4 review tasks → oracle, unspecified-high, deep.

## TODOs
> Implementation + Test = ONE task. Never separate.
> EVERY task MUST have: Agent Profile + Parallelization + QA Scenarios.

- [x] 1. Build the 2022.1 → 2023.1 parity baseline artifact

  **What to do**: Create `.sisyphus/evidence/wwise-2023-test-parity/parity-baseline.json` and `.sisyphus/evidence/task-1-parity-baseline.md`. The JSON must compare 2022.1 and 2023.1 reflected APIs, coverage statuses, Phase 2/2.1 buckets, URI additions/removals, risky-family policy, and current 2023.1 gaps. Treat 2022.1 committed resources plus audit tests as source of truth; do not rely on memory or uncommitted runtime output.
  **Must NOT do**: Do not edit runtime source or promote any API status in this task. Do not include 2024/2025.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: Requires careful cross-resource reconciliation and evidence taxonomy decisions.
  - Skills: [] - No specialized skill required.
  - Omitted: [`git-master`] - Commit happens after task tests pass, not during analysis.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: Tasks 2, 5, 7, 8, 10 | Blocked By: none

  **References** (executor has NO interview context - be exhaustive):
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:39-74` - Existing 2022/2023 count and default-version assertions.
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:137-181` - Existing 2023 coverage/deferred/WAQL count reconciliation.
  - Pattern: `tests/unit/test_2023_api_resource_coverage.py:27-42` - 2023 coverage must cover every reflected API once.
  - Pattern: `resources/coverage/2023.1/phase21-uri-policy.json:157-164` - Current 2023.1 status counts: 48 deferred, 1 evidence-only, 92 excluded, 18 supported, 22 untested.
  - Pattern: `tests/unit/test_2023_deferred_registry.py:16-32` - Deferred registry currently expects blocked statuses to match coverage.

  **Acceptance Criteria** (agent-executable only):
  - [ ] `.sisyphus/evidence/wwise-2023-test-parity/parity-baseline.json` exists and contains numeric fields: `wwise_2022.reflected_total=144`, `wwise_2022.functions=112`, `wwise_2022.topics=32`, `wwise_2023.reflected_total=181`, `wwise_2023.functions=149`, `wwise_2023.topics=32`.
  - [ ] The artifact includes arrays for `same_uri`, `new_in_2023`, `missing_from_2023`, `status_by_uri`, and `recommended_2023_bucket`.
  - [ ] `python -m pytest tests/unit/test_2023_cross_version_audit.py tests/unit/test_2023_api_resource_coverage.py -q` exits 0.

  **QA Scenarios** (MANDATORY - task incomplete without these):
  ```
  Scenario: Baseline reconciles committed resources
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2023_cross_version_audit.py tests/unit/test_2023_api_resource_coverage.py -q`; then parse `.sisyphus/evidence/wwise-2023-test-parity/parity-baseline.json` with Python and assert the counts above.
    Expected: Exit code 0; artifact has all required keys and exact counts.
    Evidence: .sisyphus/evidence/task-1-parity-baseline.md

  Scenario: No 2024/2025 leakage
    Tool: Bash
    Steps: Parse the baseline JSON and assert no string value contains `2024`, `2025`, `resources/coverage/2024`, or `resources/coverage/2025`.
    Expected: Assertion passes; artifact is 2023.1-only.
    Evidence: .sisyphus/evidence/task-1-parity-baseline-no-leakage.md
  ```

  **Commit**: YES | Message: `test(wwise): map 2023 parity baseline` | Files: `.sisyphus/evidence/wwise-2023-test-parity/parity-baseline.json`, `.sisyphus/evidence/task-1-parity-baseline*.md`

- [x] 2. Reclassify 2023.1 coverage resources to parity taxonomy

  **What to do**: Update `resources/coverage/2023.1/api-coverage.json`, `live-coverage-matrix.json`, `phase2-coverage-summary.json`, and `phase21-uri-policy.json` so every 2023.1 API has one evidence-backed bucket: `live-tested`, `sandbox-mutating-tested`, `fake-route-tested`, `evidence-only`, `conformance-only`, `wrapper-only`, `deferred`, or `excluded`. Preserve existing status fields if tests require them, but add parity-specific metadata rather than losing current compatibility. Keep all risky families deferred/excluded unless Task 1 found an already safe read-only probe.
  **Must NOT do**: Do not mark `counts_as_behavioral` or `counts_as_live_behavioral` true unless a task has real 2023.1 evidence path and assertions. Do not edit 2022.1 resources.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: Resource schema/count consistency across multiple large JSON files.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI work.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: Tasks 7, 8, 10 | Blocked By: Task 1

  **References**:
  - Pattern: `tests/unit/test_2023_api_resource_coverage.py:44-59` - Required per-entry metadata and no behavioral overclaim rule currently enforced.
  - Pattern: `tests/unit/test_2023_api_resource_coverage.py:61-85` - Manifest-only claims must not be promoted.
  - Pattern: `tests/unit/test_2023_live_coverage_matrix.py:17-39` - Live matrix must cover all reflected APIs exactly once and mirror coverage statuses.
  - Pattern: `tests/unit/test_2023_live_coverage_matrix.py:42-52` - Phase 2 summary must match matrix counts.
  - Pattern: `resources/coverage/2023.1/live-coverage-matrix.json:1-24` - Existing per-entry fields to preserve/extend.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2023_api_resource_coverage.py tests/unit/test_2023_live_coverage_matrix.py -q` exits 0.
  - [ ] All 181 `resources/coverage/2023.1/api-coverage.json` entries have a parity bucket and evidence standard.
  - [ ] All status/count summaries in `api-coverage`, `live-coverage-matrix`, `phase2-coverage-summary`, and `phase21-uri-policy` reconcile to 181.
  - [ ] No entry with `manifest_reflection_only=true` has `counts_as_behavioral=true` or `counts_as_live_behavioral=true`.

  **QA Scenarios**:
  ```
  Scenario: Coverage taxonomy is total and reconciled
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2023_api_resource_coverage.py tests/unit/test_2023_live_coverage_matrix.py -q`.
    Expected: Exit code 0; tests prove 181 entries and matching resource counts.
    Evidence: .sisyphus/evidence/task-2-coverage-taxonomy.txt

  Scenario: Manifest-only promotion is rejected
    Tool: Bash
    Steps: Run a Python assertion over `resources/coverage/2023.1/api-coverage.json` that fails if any `manifest_reflection_only` entry has behavioral or live behavioral counts set true.
    Expected: Exit code 0; zero invalid promotions.
    Evidence: .sisyphus/evidence/task-2-no-manifest-overclaim.txt
  ```

  **Commit**: YES | Message: `test(coverage): classify 2023 parity resources` | Files: `resources/coverage/2023.1/*.json`, `tests/unit/test_2023_api_resource_coverage.py`, `tests/unit/test_2023_live_coverage_matrix.py`

- [x] 3. Expand 2023.1 live read-only evidence without source mutation

  **What to do**: Extend `tests/live/test_2023_waql_live_matrix.py` and `resources/waql/2023.1/object-get-live-matrix.json` to cover the safe read-only 2023.1 surface comparable to 2022.1: object.get query variants, field-return assertions, stable object identity checks, schema-safe empty-result checks, and topic/resource evidence that can be validated without subscribing to environment-sensitive events. Write evidence under `.sisyphus/evidence/wwise-2023-test-parity/live-read-only/` and update coverage resources only for cases with passing readback assertions.
  **Must NOT do**: Do not include mutating WAQL tokens (`set`, `delete`, `create`, `import`, `move`, `rename`) in read-only cases. Do not launch against the installed SampleProject directly; keep sandbox launch behavior.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: Requires hands-on live test expansion with careful safety checks.
  - Skills: [] - No specialized skill required.
  - Omitted: [`playwright`] - No browser/UI automation.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: Tasks 7, 8, 10 | Blocked By: Task 1

  **References**:
  - Pattern: `tests/live/test_2023_waql_live_matrix.py:37-76` - Existing sandboxed read-only live test flow.
  - Pattern: `tests/live/test_2023_waql_live_matrix.py:79-93` - Matrix metadata and mutation-token guard.
  - Pattern: `tests/live/test_2023_waql_live_matrix.py:103-130` - Result-count and field assertions.
  - Pattern: `tests/live/test_2023_waql_live_matrix.py:133-151` - Existing evidence-writing pattern.
  - Pattern: `tests/live/test_2023_reflection_inventory.py:43-97` - Sandbox launch, manifest audit, source hash/mtime immutability checks.

  **Acceptance Criteria**:
  - [ ] `WWISE_VERSION=2023.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" WWISE_LIVE=1 python -m pytest tests/live/test_2023_live_prerequisites.py tests/live/test_2023_reflection_inventory.py tests/live/test_2023_waql_live_matrix.py -q` exits 0.
  - [ ] Every promoted live read-only case has an evidence JSON path and exact expected/result assertions.
  - [ ] Source mtime/hash assertions remain present for installed SampleProject source.

  **QA Scenarios**:
  ```
  Scenario: Live read-only matrix passes against 2023.1 sandbox
    Tool: Bash
    Steps: Run the exact WWISE_VERSION=2023.1 live command from this task's acceptance criteria.
    Expected: Exit code 0; evidence files written under `.sisyphus/evidence/wwise-2023-test-parity/live-read-only/`; installed source is unchanged.
    Evidence: .sisyphus/evidence/task-3-live-read-only.txt

  Scenario: Mutating query is rejected before WAAPI call
    Tool: Bash
    Steps: Temporarily inject a copy of one matrix case containing `delete` in WAQL using a test-local monkeypatch or unit helper, then run only the mutation guard assertion.
    Expected: Assertion fails before client.call; no Wwise project mutation occurs.
    Evidence: .sisyphus/evidence/task-3-read-only-guard.txt
  ```

  **Commit**: YES | Message: `test(live): expand 2023 read-only parity evidence` | Files: `tests/live/test_2023_waql_live_matrix.py`, `resources/waql/2023.1/object-get-live-matrix.json`, `resources/coverage/2023.1/*.json`, `.sisyphus/evidence/wwise-2023-test-parity/live-read-only/*`

- [x] 4. Expand 2023.1 destructive sandbox parity for safe mutating families

  **What to do**: Add/extend destructive sandbox tests for safe mutating families already represented in 2023.1 support: object create/set/delete, audio import, soundbank inclusions, switchContainer assignment, and any additional 2022.1 safe sandbox-mutating family identified by Task 1 that does not fall into risky excluded families. Each test must create unique names, read back state, remove/cleanup objects, and rely on `Destructive2023SandboxRuntime` source-immutability proof.
  **Must NOT do**: Do not run profiler, transport, soundengine, UI, CLI, remote, or debug mutation probes. Do not target installed SampleProject or `tests/_org/2023.1`.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: Live destructive tests require careful cleanup and proof.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI work.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: Tasks 6, 7, 8, 10 | Blocked By: Task 1

  **References**:
  - Pattern: `tests/destructive/test_2023_project_mutation_sandbox.py:71-103` - Existing object create/set/delete readback cleanup test.
  - Pattern: `tests/destructive/test_2023_soundbank_audio_sandbox.py:77-115` - Existing audio import generated WAV readback cleanup.
  - Pattern: `tests/destructive/test_2023_soundbank_audio_sandbox.py:117-142` - Existing soundbank inclusion replace/read/remove cleanup.
  - Pattern: `tests/destructive/test_2023_switchcontainer_assignment_sandbox.py:75-128` - Existing switchContainer assignment add/get/remove cleanup.
  - Pattern: `wwise_waapi/destructive_2023_sandbox.py:72-95` - Runtime setup and fail-closed conversion to `DestructiveSandboxUnavailable`.
  - Pattern: `wwise_waapi/destructive_2023_sandbox.py:146-152` - Source immutability assertions.

  **Acceptance Criteria**:
  - [ ] `WWISE_VERSION=2023.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 python -m pytest tests/destructive/test_2023_project_mutation_sandbox.py tests/destructive/test_2023_soundbank_audio_sandbox.py tests/destructive/test_2023_switchcontainer_assignment_sandbox.py -q` exits 0.
  - [ ] Each mutating test has create/readback/delete or replace/read/remove assertions.
  - [ ] Each promoted mutating API has evidence path recorded in coverage resources.

  **QA Scenarios**:
  ```
  Scenario: Destructive sandbox parity passes and cleans up
    Tool: Bash
    Steps: Run the exact WWISE_VERSION=2023.1 destructive command from this task's acceptance criteria.
    Expected: Exit code 0; no sandbox path remains unless keep-on-failure is enabled; installed SampleProject hash/mtime unchanged.
    Evidence: .sisyphus/evidence/task-4-destructive-sandbox.txt

  Scenario: Mutating tests are skipped without explicit gate
    Tool: Bash
    Steps: Run `WWISE_VERSION=2023.1 python -m pytest tests/destructive/test_2023_project_mutation_sandbox.py -q` without `WWISE_LIVE=1` or `WWISE_DESTRUCTIVE=1`.
    Expected: Module-level skip; no WwiseConsole launch; exit code 0 or pytest skip-only success.
    Evidence: .sisyphus/evidence/task-4-destructive-gate.txt
  ```

  **Commit**: YES | Message: `test(destructive): expand 2023 sandbox parity` | Files: `tests/destructive/test_2023_*.py`, `resources/coverage/2023.1/*.json`, `.sisyphus/evidence/wwise-2023-test-parity/destructive/*`

- [x] 5. Lock risky-family deferred/excluded policy with evidence

  **What to do**: Update `resources/deferred/2023.1.json` and `resources/coverage/2023.1/wrapper-only-category-policy.json` so profiler, transport, soundengine, UI, CLI, remote, and debug remain deferred/excluded with explicit 2023.1 rationale, future review triggers, and no behavioral/live promotion. Incorporate Task 1 findings for any 2023-specific new APIs in these families.
  **Must NOT do**: Do not add live probes for these families except named safe probes already proven by existing tests. Do not remove excluded family assertions.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: Policy-heavy classification task with risk guardrails.
  - Skills: [] - No specialized skill required.
  - Omitted: [`playwright`] - UI APIs are not to be automated in this plan.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: Tasks 7, 8, 10 | Blocked By: Task 1

  **References**:
  - Pattern: `tests/unit/test_2023_deferred_registry.py:16-32` - Deferred entries must match blocked coverage statuses.
  - Pattern: `tests/unit/test_2023_deferred_registry.py:34-43` - Deferred metadata/status model requirements.
  - Pattern: `tests/unit/test_2023_deferred_registry.py:45-62` - Required excluded families and counts.
  - Pattern: `resources/coverage/2023.1/wrapper-only-category-policy.json:1-112` - Existing excluded family rationales/counts.
  - Pattern: `resources/coverage/2023.1/phase21-uri-policy.json:61-155` - Existing excluded URI list and live-tested URI list.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2023_deferred_registry.py tests/unit/test_2023_api_resource_coverage.py -q` exits 0.
  - [ ] Deferred registry entries exactly equal 2023.1 coverage entries with `coverage_status in {"deferred", "excluded"}`.
  - [ ] Required excluded families remain present: profiler, transport, soundengine, UI, CLI, remote, debug.
  - [ ] Every excluded/deferred entry has `evidence_source`, `blocking_condition`, `substitute_test`, and `future_review_trigger`.

  **QA Scenarios**:
  ```
  Scenario: Risky families remain explicitly blocked
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2023_deferred_registry.py tests/unit/test_2023_api_resource_coverage.py -q`.
    Expected: Exit code 0; required excluded family assertions pass.
    Evidence: .sisyphus/evidence/task-5-risky-family-policy.txt

  Scenario: No risky family accidentally promoted
    Tool: Bash
    Steps: Parse `resources/coverage/2023.1/api-coverage.json` and assert every profiler/transport/soundengine/UI/CLI/remote/debug entry has `coverage_status` deferred or excluded and both behavioral booleans false.
    Expected: Exit code 0; zero accidental promotions.
    Evidence: .sisyphus/evidence/task-5-no-risky-promotion.txt
  ```

  **Commit**: YES | Message: `test(coverage): preserve 2023 risky api deferrals` | Files: `resources/deferred/2023.1.json`, `resources/coverage/2023.1/wrapper-only-category-policy.json`, `resources/coverage/2023.1/*.json`, `tests/unit/test_2023_deferred_registry.py`

- [x] 6. Strengthen destructive fail-closed and immutability tests

  **What to do**: Add unit or destructive-gate tests proving missing `WWISE_LIVE`, missing `WWISE_DESTRUCTIVE`, missing/unsafe `WWISE_SANDBOX_ROOT`, installed SampleProject targets, and `tests/_org/2023.1` targets are rejected or skipped before mutation. Preserve `Destructive2023SandboxRuntime` behavior and add tests around `require_2023_live_destructive_prerequisites` and `require_2023_sandbox_copy_target` as needed.
  **Must NOT do**: Do not weaken `LiveEnvironmentError`/`SandboxFixtureError` messages. Do not allow destructive tests to use default SampleProject directly.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: Safety-critical negative-path tests.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI work.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: Tasks 7, 8, 10 | Blocked By: Task 4

  **References**:
  - Pattern: `wwise_waapi/live_environment.py:188-218` - Destructive environment fail-fast checks for sandbox root, fixture project, immutable sources.
  - Pattern: `wwise_waapi/live_environment.py:150-185` - Live prerequisite fail-fast behavior.
  - Pattern: `wwise_waapi/destructive_2023_sandbox.py:166-184` - Exact 2023.1 live/destructive prerequisite checks.
  - Pattern: `wwise_waapi/destructive_2023_sandbox.py:187-206` - Sandbox copy target proof.
  - Pattern: `wwise_waapi/sandbox_fixture.py:140-198` - Sandbox copy metadata/hash proof.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit -q` exits 0.
  - [ ] At least one test asserts unsafe sandbox roots under `tests/_org` are rejected.
  - [ ] At least one test asserts installed SampleProject cannot be selected as active destructive project.
  - [ ] At least one test asserts missing destructive gates skip or fail before WwiseConsole launch.

  **QA Scenarios**:
  ```
  Scenario: Unsafe sandbox paths fail closed
    Tool: Bash
    Steps: Run the new/updated unit tests targeting `require_destructive_environment` and `require_2023_sandbox_copy_target`.
    Expected: Exit code 0; unsafe installed or `tests/_org` paths raise explicit safety errors.
    Evidence: .sisyphus/evidence/task-6-fail-closed.txt

  Scenario: Missing destructive gates do not launch Wwise
    Tool: Bash
    Steps: Run `WWISE_VERSION=2023.1 python -m pytest tests/destructive/test_2023_project_mutation_sandbox.py -q` without live/destructive gates.
    Expected: Module-level skip before import-time runtime setup; no WwiseConsole process launched.
    Evidence: .sisyphus/evidence/task-6-missing-gates.txt
  ```

  **Commit**: YES | Message: `test(live): harden 2023 destructive safety gates` | Files: `wwise_waapi/live_environment.py`, `wwise_waapi/destructive_2023_sandbox.py`, `wwise_waapi/sandbox_fixture.py`, `tests/unit/*`, `tests/destructive/test_2023_*.py`

- [x] 7. Update audit tests to enforce parity counts and evidence-backed promotions

  **What to do**: Update unit/audit tests so 2023.1 parity cannot regress: all 181 APIs classified exactly once; coverage/matrix/summary/deferred counts reconcile; no unsupported promotion; default version stays 2022.1; explicit 2023.1 resource lookups never read 2022.1 fallback paths. The tests must permit new evidence-backed 2023.1 behavioral counts from Tasks 3-4 while rejecting manifest-only claims.
  **Must NOT do**: Do not hardcode obsolete `live_tested == 0` if Tasks 3-4 legitimately promote live evidence. Replace with evidence-backed assertions.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Reason: Cross-resource audit updates after resource/live/destructive changes.
  - Skills: [] - No specialized skill required.
  - Omitted: [`playwright`] - No UI.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: Task 10 | Blocked By: Tasks 2, 3, 4, 5, 6

  **References**:
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:39-74` - Default 2022.1 and explicit 2023.1 dispatcher checks.
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:76-110` - 2023 resource lookups must not touch 2022/global fallbacks.
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:137-181` - Existing count checks currently assume no live behavioral coverage.
  - Pattern: `tests/unit/test_2023_docs_contract.py:20-43` - Docs must include exact paths and avoid overclaiming.
  - Pattern: `tests/unit/test_2023_live_coverage_matrix.py:27-39` - Existing no-manifest-only live claim assertions.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2023_cross_version_audit.py tests/unit/test_2023_docs_contract.py tests/unit/test_2023_live_coverage_matrix.py -q` exits 0.
  - [ ] Tests fail if a promoted 2023.1 entry lacks an evidence path under `.sisyphus/evidence/wwise-2023-test-parity/`, `resources/waql/2023.1/`, or another explicit 2023.1 evidence source.
  - [ ] Tests fail if any explicit 2023.1 lookup reads `resources/coverage/2022.1`, `resources/deferred/2022.1`, or unversioned semantic references.

  **QA Scenarios**:
  ```
  Scenario: Audit suite validates evidence-backed parity
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2023_cross_version_audit.py tests/unit/test_2023_docs_contract.py tests/unit/test_2023_live_coverage_matrix.py -q`.
    Expected: Exit code 0; promoted counts are accepted only with evidence paths.
    Evidence: .sisyphus/evidence/task-7-audit-parity.txt

  Scenario: 2022 fallback guard remains active
    Tool: Bash
    Steps: Run the guarded read_text test from `test_explicit_2023_resource_lookups_never_read_2022_or_global_semantic_paths`.
    Expected: Exit code 0; no forbidden 2022/global path touched.
    Evidence: .sisyphus/evidence/task-7-no-fallback.txt
  ```

  **Commit**: YES | Message: `test(wwise): enforce 2023 parity audits` | Files: `tests/unit/test_2023_*.py`

- [x] 8. Produce review packet and docs/evals without full-coverage overclaims

  **What to do**: Update `references/phase2-user-review-packet.md`, `references/eval-review-workflow.md`, `references/long-run-runbook.md`, `SKILL.md`, and `evals/evals.json` only where claims need to reflect 2023.1 parity evidence. Create `.sisyphus/evidence/wwise-2023-test-parity/parity-review-packet.md` summarizing promoted APIs, deferred/excluded APIs, evidence paths, exact live/destructive commands, source immutability proof, and Windows non-blocking caveat.
  **Must NOT do**: Do not claim “all 2023.1 APIs are live-tested” or “full support for 2023.1” unless every API has live behavioral evidence, which is not expected under the chosen risky-family policy.

  **Recommended Agent Profile**:
  - Category: `writing` - Reason: Documentation and review packet wording must be precise and non-overclaiming.
  - Skills: [] - No specialized skill required.
  - Omitted: [`humanizer-zh`] - Technical repo docs are English and assertion-driven.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: Task 10 | Blocked By: Tasks 2, 3, 4, 5, 6

  **References**:
  - Pattern: `tests/unit/test_2023_docs_contract.py:20-43` - Docs must include exact 2023 paths and avoid forbidden positive claims.
  - Pattern: `tests/unit/test_2023_docs_contract.py:46-70` - Eval examples must be version-scoped and avoid path leakage.
  - Pattern: `tests/live/test_2023_live_prerequisites.py:17-23` - Exact 2023.1 WwiseConsole/SampleProject paths.
  - Pattern: `wwise_waapi/destructive_2023_sandbox.py:146-152` - Source immutability proof to describe.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2023_docs_contract.py -q` exits 0.
  - [ ] `.sisyphus/evidence/wwise-2023-test-parity/parity-review-packet.md` includes sections: `Promoted Evidence`, `Deferred/Excluded`, `Commands Run`, `Source Immutability`, `Windows Caveat`, `Known Non-Goals`.
  - [ ] Docs state Windows validation is non-blocking evidence/caveat, not a hard gate.

  **QA Scenarios**:
  ```
  Scenario: Docs avoid full-coverage overclaims
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2023_docs_contract.py -q`.
    Expected: Exit code 0; forbidden positive claims are absent.
    Evidence: .sisyphus/evidence/task-8-docs-contract.txt

  Scenario: Review packet is complete
    Tool: Bash
    Steps: Parse `.sisyphus/evidence/wwise-2023-test-parity/parity-review-packet.md` and assert required section headings exist.
    Expected: Exit code 0; all required headings present.
    Evidence: .sisyphus/evidence/task-8-review-packet.txt
  ```

  **Commit**: YES | Message: `docs(wwise): document 2023 parity evidence` | Files: `references/*.md`, `SKILL.md`, `evals/evals.json`, `.sisyphus/evidence/wwise-2023-test-parity/parity-review-packet.md`, `tests/unit/test_2023_docs_contract.py`

- [x] 9. Verify default Wwise-free behavior and 2023 explicit opt-in gates

  **What to do**: Run and, if needed, update tests that prove default pytest remains Wwise-free and default dispatch remains 2022.1. Ensure 2023.1 live/destructive tests skip unless explicitly opted in. Record command output in `.sisyphus/evidence/task-9-default-and-gates.txt`.
  **Must NOT do**: Do not require WwiseConsole for `python -m pytest -q`. Do not set repository-global environment defaults to 2023.1.

  **Recommended Agent Profile**:
  - Category: `quick` - Reason: Command verification and small test adjustments only.
  - Skills: [] - No specialized skill required.
  - Omitted: [`git-master`] - Only use if committing after verification.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: Task 10 | Blocked By: Tasks 6, 7

  **References**:
  - Pattern: `wwise_waapi/live_environment.py:22-23` - Supported/default live version remains 2022.1.
  - Pattern: `wwise_waapi/live_environment.py:94-113` - Environment parser defaults to 2022.1 unless `WWISE_VERSION` set.
  - Pattern: `tests/destructive/test_2023_project_mutation_sandbox.py:9-15` - Destructive module-level skip gates.
  - Pattern: `tests/live/test_2023_live_prerequisites.py:42-57` - Explicit 2023 live prerequisites.
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:47-73` - Default dispatcher 2022.1 and explicit 2023.1.

  **Acceptance Criteria**:
  - [ ] `python -m pytest -q` exits 0 without WwiseConsole requirement.
  - [ ] `WWISE_VERSION=2023.1 python -m pytest tests/destructive/test_2023_project_mutation_sandbox.py -q` skips safely without WwiseConsole launch.
  - [ ] `python -m pytest tests/unit/test_2023_cross_version_audit.py -q` exits 0 and proves default dispatcher remains 2022.1.

  **QA Scenarios**:
  ```
  Scenario: Default suite is Wwise-free
    Tool: Bash
    Steps: Run `python -m pytest -q` with no WWISE_LIVE/WWISE_DESTRUCTIVE env vars.
    Expected: Exit code 0; no live/destructive WwiseConsole launch required.
    Evidence: .sisyphus/evidence/task-9-default-suite.txt

  Scenario: 2023 destructive explicit opt-in gate holds
    Tool: Bash
    Steps: Run `WWISE_VERSION=2023.1 python -m pytest tests/destructive/test_2023_project_mutation_sandbox.py -q`.
    Expected: Safe skip before runtime setup; no project mutation.
    Evidence: .sisyphus/evidence/task-9-destructive-skip.txt
  ```

  **Commit**: YES | Message: `test(wwise): verify 2023 opt-in gates` | Files: `tests/unit/*`, `tests/live/*`, `tests/destructive/*`, `.sisyphus/evidence/task-9-*.txt`

- [ ] 10. Final resource/evidence reconciliation pass

  **What to do**: Reconcile all resources after Tasks 2-9. Confirm no orphan 2023.1 APIs, no stale `live_tested == 0` assertions if evidence exists, no missing evidence files, no `.sisyphus/runtime` artifacts staged, and no docs contradict the risky-family/Windows decisions. Update `.sisyphus/evidence/wwise-2023-test-parity/parity-review-packet.md` with final command results.
  **Must NOT do**: Do not introduce new feature scope. Do not silently drop APIs to make counts pass.

  **Recommended Agent Profile**:
  - Category: `deep` - Reason: End-to-end consistency pass across resources, tests, evidence, docs.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: F1-F4 | Blocked By: Tasks 7, 8, 9

  **References**:
  - Pattern: `tests/unit/test_2023_api_resource_coverage.py:27-42` - API coverage exact-once contract.
  - Pattern: `tests/unit/test_2023_live_coverage_matrix.py:17-52` - Matrix and summary reconciliation.
  - Pattern: `tests/unit/test_2023_deferred_registry.py:16-62` - Deferred/excluded reconciliation.
  - Pattern: `tests/unit/test_2023_docs_contract.py:20-70` - Documentation/eval non-overclaim contract.
  - Pattern: `tests/live/test_2023_reflection_inventory.py:94-96` - Live sandbox source immutability and cleanup checks.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2023_api_resource_coverage.py tests/unit/test_2023_live_coverage_matrix.py tests/unit/test_2023_deferred_registry.py tests/unit/test_2023_cross_version_audit.py tests/unit/test_2023_docs_contract.py -q` exits 0.
  - [ ] Exact 2023.1 live command exits 0.
  - [ ] Exact 2023.1 destructive command exits 0.
  - [ ] `python -m pytest -q` exits 0.
  - [ ] `.sisyphus/evidence/wwise-2023-test-parity/parity-review-packet.md` lists final promoted/deferred/excluded counts and command results.

  **QA Scenarios**:
  ```
  Scenario: Full parity verification commands pass
    Tool: Bash
    Steps: Run the unit audit command, exact live command, exact destructive command, and default `python -m pytest -q`.
    Expected: All exit 0; evidence packet updated with command outputs.
    Evidence: .sisyphus/evidence/task-10-final-reconciliation.txt

  Scenario: No runtime artifacts staged
    Tool: Bash
    Steps: Run `git status --short` and inspect output for `.sisyphus/runtime` or copied SampleProject artifacts.
    Expected: No `.sisyphus/runtime` files are staged or tracked; only intended resource/test/docs/evidence files appear.
    Evidence: .sisyphus/evidence/task-10-no-runtime-artifacts.txt
  ```

  **Commit**: YES | Message: `test(wwise): reconcile 2023 parity evidence` | Files: `resources/coverage/2023.1/*.json`, `resources/deferred/2023.1.json`, `tests/unit/test_2023_*.py`, `tests/live/test_2023_*.py`, `tests/destructive/test_2023_*.py`, `references/*.md`, `evals/evals.json`, `.sisyphus/evidence/wwise-2023-test-parity/*`

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [ ] F1. Plan Compliance Audit — oracle
- [ ] F2. Code Quality Review — unspecified-high
- [ ] F3. Real Manual QA — unspecified-high (+ Bash/live commands; Playwright not required because no UI)
- [ ] F4. Scope Fidelity Check — deep

## Commit Strategy
- Commit after each completed task or tightly related pair when tests for that task pass.
- Use concise messages such as `test(wwise): map 2023 parity baseline`, `test(live): expand 2023 read-only evidence`, `test(destructive): expand 2023 sandbox parity`, `docs(wwise): document 2023 parity evidence`.
- Do not push unless explicitly requested.
- Do not commit live runtime sandboxes under `.sisyphus/runtime/`.
- Commit `.sisyphus/evidence/wwise-2023-test-parity/` artifacts only if they are intended review evidence and contain no machine-local secrets beyond approved Wwise install paths.

## Success Criteria
- All 181 reflected 2023.1 APIs are accounted for exactly once.
- 2023.1 behavioral/live/destructive counts are evidence-backed and reconcile across resources/tests.
- Risky families remain deferred/excluded with clear evidence and future review triggers.
- Default pytest remains Wwise-free and 2022.1-default.
- Explicit 2023.1 live and destructive suites pass on macOS with exact 2023.1 paths.
- Review packet states Windows is non-blocking evidence/caveat, not a hard gate.
