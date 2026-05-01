# Wwise 2024.1.13 WAAPI Integration and Test Coverage

## TL;DR
> **Summary**: Add Wwise 2024.1 as a version-isolated, fail-closed WAAPI lane and include parity-scale test coverage in the same first execution plan. Use completed 2023.1 parity work as the template while discovering 2024.1 counts from live reflection.
> **Deliverables**: 2024.1 version/env support; manifest/semantic/coverage/deferred/WAQL resources; fixture and sandbox safety; live/destructive evidence; docs/evals review packet; final reconciliation.
> **Effort**: XL
> **Parallel**: YES - 4 waves
> **Critical Path**: Task 1 → Task 2 → Task 3 → Tasks 5-8 → Tasks 9-10 → Task 13 → Final Verification Wave

## Context
### Original Request
- Create a Wwise 2024 WAAPI integration and test coverage plan.
- Use `references/wwise-version-upgrade-2023-first.md` as the 2024 planning reference despite the filename.
- User explicitly wants implementation/connectivity and test coverage in the first plan, not a second follow-up test plan.

### Confirmed 2024.1.13 Inputs
- Version key for resources/env/tests: `2024.1`.
- Installed build/path suffix: `2024.1.13.9056`.
- WwiseConsole: `/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh`.
- SampleProject: `/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj`.
- NotebookLM active library: `wwise-2024.1-docs`.

### Research Summary
- 2023.1 parity is complete and is the implementation template: 181 reflected APIs, one live-tested read-only URI, ten sandbox-mutating URIs, 135 deferred/excluded entries, 92 risky-family exclusions, zero risky-family accidental promotions.
- Version/default patterns: `wwise_waapi/dispatcher.py:23-26`, `wwise_waapi/versions.py:16-29`.
- Live env exact-path patterns: `wwise_waapi/live_environment.py:22-35`, `wwise_waapi/live_environment.py:79-91`, `wwise_waapi/live_environment.py:150-218`.
- 2023 destructive sandbox template: `wwise_waapi/destructive_2023_sandbox.py:58-97`, `wwise_waapi/destructive_2023_sandbox.py:169-209`.
- Cross-version and parity audits: `tests/unit/test_2023_cross_version_audit.py:61-131`, `tests/unit/test_2023_cross_version_audit.py:159-274`, `tests/unit/test_2023_api_resource_coverage.py:57-153`.
- Docs/no-overclaim contract: `tests/unit/test_2023_docs_contract.py:21-112`.

### Oracle / Metis Gaps Addressed
- Add `2024.1` to fail-closed contracts before adding resources to prevent silent fallback.
- Treat parity as structure/policy parity; discover 2024 reflected API counts from live reflection instead of assuming 181.
- Keep 2024 support version-isolated; reject 2022/2023/global semantic fallback for explicit 2024.1.
- Add connectivity, missing-path, stale-process, sandbox-copy-failure, and generated-evidence-rewrite guardrails.
- Do not broaden into a generalized multi-version framework rewrite unless strictly necessary.

## Work Objectives
### Core Objective
Support Wwise 2024.1.13 WAAPI resources and tests as an explicit opt-in version lane, with parity-scale coverage governance included from the first plan.

### Deliverables
- `resources/manifest/2024.1/` split manifest resources.
- `references/semantic/2024.1/` and `resources/semantic/2024.1/source_notes.json` grounded by `wwise-2024.1-docs`.
- `resources/coverage/2024.1/{api-coverage.json,live-coverage-matrix.json,phase2-coverage-summary.json,phase21-uri-policy.json}`.
- `resources/deferred/2024.1.json` and `resources/waql/2024.1/`.
- `tests/_org/2024.1/` immutable fixture metadata and tests.
- 2024 unit/live/destructive tests and evidence under `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/`.
- 2024 docs/evals/review packet without full-support overclaims.

### Definition of Done
- `python -m pytest -q` passes without WwiseConsole.
- Exact 2024.1 live command exits 0 or fails/skips with explicit prerequisite evidence when unavailable.
- Exact 2024.1 destructive command exits 0 for planned sandbox-mutating cases or fails/skips safely before mutation when unavailable.
- 2024.1 resources reconcile: reflected APIs, coverage entries, matrix entries, policy assignments, deferred registry, source notes, and docs/evals.
- No `.sisyphus/runtime` or copied SampleProject artifacts are tracked/staged.

### Must Have
- Default dispatcher/runtime remains `2022.1` unless `WWISE_VERSION=2024.1` is explicit.
- `2024.1` never falls back to 2022.1, 2023.1, `resources/manifest/2024`, or global unversioned semantic docs.
- Risky families (`profiler`, `transport`, `soundengine`, `UI`, `CLI`, `remote`, `debug`) remain excluded/deferred unless fresh 2024.1 evidence and gates explicitly justify promotion.
- Manifest reflection, skipped live tests, and skipped destructive tests are not behavioral proof.

### Must NOT Have
- No 2025 implementation.
- No broad rewrite of the builder/dispatcher architecture unless required by failing 2024.1 evidence.
- No mutation of installed SampleProject or `tests/_org/2024.1`.
- No claims that all 2024.1 APIs are live-tested or fully behavior-tested.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: tests-after with targeted TDD-style guard tests before each risky production change.
- QA policy: Every task has agent-executed happy/failure scenarios.
- Evidence root: `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/` plus task-specific `.sisyphus/evidence/task-2024-*.txt`.
- Live/destructive command paths must use the exact 2024.1.13 WwiseConsole and SampleProject paths above.

## Execution Strategy
### Parallel Execution Waves
- Wave 1: Tasks 1-4 (version lane, fixture, manifest, isolation tests) mostly sequential with Task 4 after Tasks 1-3.
- Wave 2: Tasks 5-8 (semantic docs, coverage/deferred resources, unit audits, live read-only evidence) after manifest exists.
- Wave 3: Tasks 9-12 (destructive sandbox, destructive evidence, docs/evals, default gates) after resources and safety gates.
- Wave 4: Task 13 final reconciliation.

### Dependency Matrix
- T1 blocks T3, T4, T8, T9, T12.
- T2 blocks T3, T8, T9, T10.
- T3 blocks T5, T6, T7, T8, T13.
- T5 and T6 block T7, T11, T13.
- T8 and T10 block promotion updates and T13.
- T13 blocks F1-F4.

### Agent Dispatch Summary
- Wave 1: 4 tasks → unspecified-high/deep.
- Wave 2: 4 tasks → writing/unspecified-high.
- Wave 3: 4 tasks → unspecified-high/writing/quick.
- Wave 4: 1 task → deep.

## TODOs

- [x] 1. Add fail-closed 2024.1 version and live environment contracts

  **What to do**: Add `WWISE_2024_1_VERSION_KEY="2024.1"`, `WWISE_2024_1_BUILD="2024.1.13.9056"`, and a `WwiseVersionContract` in `wwise_waapi/versions.py`. Add exact 2024 WwiseConsole/SampleProject constants, `LIVE_VERSION_PATHS` entry with `require_exact_paths=True`, and immutable installed SampleProject root in `wwise_waapi/live_environment.py`. Add 2024 unit tests mirroring `test_2023_live_environment_contract.py` and version contract tests.
  **Must NOT do**: Do not change `DEFAULT_WWISE_VERSION` from `2022.1`. Do not make `2024` an alias for `2024.1`.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Version/env contracts are cross-cutting safety code.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: Tasks 3, 4, 8, 9, 12 | Blocked By: none

  **References**:
  - Pattern: `wwise_waapi/versions.py:16-29` - Add fail-closed version contracts.
  - Pattern: `wwise_waapi/live_environment.py:22-35` - Add exact path constants.
  - Pattern: `wwise_waapi/live_environment.py:79-91` - Add version-specific path entry.
  - Test: `tests/unit/test_2023_live_environment_contract.py:57-186` - Port exact-path/no-fallback/destructive-target assertions.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2024_version_contract.py tests/unit/test_2024_live_environment_contract.py -q` exits 0.
  - [ ] Default dispatcher version remains `2022.1`.
  - [ ] `WWISE_VERSION=2024.1` live prereqs require exact 2024.1.13 paths and never fallback to 2022.1/2023.1.

  **QA Scenarios**:
  ```
  Scenario: Exact 2024 env accepted
    Tool: Bash
    Steps: Run the new 2024 live environment contract tests.
    Expected: Exit 0; tests assert exact console/sample paths and version key.
    Evidence: .sisyphus/evidence/task-2024-1-version-env.txt

  Scenario: Wrong path fails closed
    Tool: Bash
    Steps: Run tests with monkeypatched wrong console/sample paths.
    Expected: LiveEnvironmentError includes exact 2024.1 WwiseConsole and SampleProject path requirements.
    Evidence: .sisyphus/evidence/task-2024-1-fail-closed.txt
  ```

  **Commit**: YES | Message: `feat(wwise): add 2024 version contracts` | Files: `wwise_waapi/versions.py`, `wwise_waapi/live_environment.py`, `tests/unit/test_2024_*.py`

- [x] 2. Create immutable 2024.1 fixture source from installed SampleProject

  **What to do**: Copy `/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj` and required `.wwu` project files into `tests/_org/2024.1/`. Generate `fixture-metadata.json`, `fixture-manifest.json`, and `README.md` matching 2023.1 fixture conventions. Exclude generated banks, logs, caches, audio outputs, and runtime files.
  **Must NOT do**: Do not mutate or commit the installed SampleProject; do not copy generated artifacts.

  **Recommended Agent Profile**:
  - Category: `deep` - Requires filesystem evidence and fixture provenance.
  - Skills: [] - No specialized skill required.
  - Omitted: [`git-master`] - Commit happens after verification.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: Tasks 3, 8, 9, 10 | Blocked By: Task 1

  **References**:
  - Pattern: `tests/_org/2023.1/README.md` - Immutable fixture warning.
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:277-295` - Fixture metadata/runtime-artifact assertions.
  - External: `references/wwise-version-upgrade-2023-first.md:31-67` - Exact 2024 SampleProject and fixture guidance.

  **Acceptance Criteria**:
  - [ ] `tests/_org/2024.1/SampleProject.wproj` exists.
  - [ ] `python -m pytest tests/unit/test_2024_fixture_inventory.py -q` exits 0.
  - [ ] Fixture manifest contains only `.wproj`, `.wwu`, and approved documentation/metadata files.

  **QA Scenarios**:
  ```
  Scenario: Fixture provenance recorded
    Tool: Bash
    Steps: Run fixture inventory test.
    Expected: Metadata references build 2024.1.13.9056 and source SampleProject path exactly.
    Evidence: .sisyphus/evidence/task-2024-2-fixture.txt

  Scenario: Runtime artifacts excluded
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2024_fixture_inventory.py -q`.
    Expected: No `.akd`, `.bnk`, `.wem`, `.log`, `GeneratedSoundBanks`, or `Logs` paths in fixture manifest.
    Evidence: .sisyphus/evidence/task-2024-2-no-runtime.txt
  ```

  **Commit**: YES | Message: `test(wwise): add 2024 fixture source` | Files: `tests/_org/2024.1/*`, `tests/unit/test_2024_fixture_inventory.py`

- [x] 3. Generate 2024.1 live reflection manifest resources

  **What to do**: Use exact 2024 live env to reflect functions, topics, and schemas into `resources/manifest/2024.1/{manifest.json,functions.json,topics.json,schemas.json}`. Include build metadata `2024.1.13.9056`, path-scrubbed reflection data, source URIs, audit counts, and schema failure count. Record exact command output and discovered counts.
  **Must NOT do**: Do not place files under `resources/manifest/2024/`; do not reuse 2023 manifest counts.

  **Recommended Agent Profile**:
  - Category: `deep` - Live reflection and deterministic generated resources.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: Tasks 4, 5, 6, 7, 8, 13 | Blocked By: Tasks 1, 2

  **References**:
  - Pattern: `wwise_waapi/manifest.py:156-198` - Reflection manifest builder.
  - Pattern: `wwise_waapi/manifest.py:201-218` - Deterministic JSON writer.
  - Pattern: `tests/unit/test_2023_manifest_resources.py` - Manifest resource assertions.

  **Acceptance Criteria**:
  - [ ] `resources/manifest/2024.1/manifest.json` exists and reports `wwise_version_target == "2024.1"`.
  - [ ] `python -m pytest tests/unit/test_2024_manifest_resources.py -q` exits 0.
  - [ ] Evidence records reflected function/topic/schema counts discovered from 2024.1.

  **QA Scenarios**:
  ```
  Scenario: Live reflection succeeds
    Tool: Bash
    Steps: Run the 2024.1 manifest generation command with exact console/sample paths and `WWISE_LIVE=1`.
    Expected: Exit 0; split manifest files written under `resources/manifest/2024.1/`.
    Evidence: .sisyphus/evidence/task-2024-3-manifest-reflection.txt

  Scenario: Manifest isolation holds
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2024_manifest_resources.py -q`.
    Expected: No `resources/manifest/2022.1`, `resources/manifest/2023.1`, or `resources/manifest/2024` fallback in explicit 2024 checks.
    Evidence: .sisyphus/evidence/task-2024-3-no-fallback.txt
  ```

  **Commit**: YES | Message: `test(wwise): reflect 2024 manifest resources` | Files: `resources/manifest/2024.1/*.json`, `tests/unit/test_2024_manifest_resources.py`, `.sisyphus/evidence/task-2024-3-*.txt`

- [x] 4. Add 2024 cross-version isolation and default-dispatch audits

  **What to do**: Port 2023 cross-version tests to `tests/unit/test_2024_cross_version_audit.py`. Assert default remains 2022.1, explicit 2024.1 dispatch dry-run succeeds, explicit 2024.1 resource reads never touch 2022.1, 2023.1, `resources/manifest/2024`, or global semantic references, and no 2025 resources are introduced.
  **Must NOT do**: Do not make 2024.1 default; do not use broad monkeypatches that hide real fallback reads.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Safety-critical cross-version isolation.
  - Skills: [] - No specialized skill required.
  - Omitted: [`playwright`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: Tasks 7, 12, 13 | Blocked By: Tasks 1, 3

  **References**:
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:61-131` - Default and no-fallback guard.
  - Pattern: `wwise_waapi/dispatcher.py:23-26` - Default version stays 2022.1.
  - Pattern: `wwise_waapi/dispatcher.py:94-180` - Explicit dry-run dispatch path.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2024_cross_version_audit.py -q` exits 0.
  - [ ] Test fails if explicit 2024.1 lookup reads 2022/2023/global resources.
  - [ ] Test fails if `DEFAULT_WWISE_VERSION` changes from 2022.1.

  **QA Scenarios**:
  ```
  Scenario: Explicit 2024 resource isolation
    Tool: Bash
    Steps: Run the new cross-version audit.
    Expected: Exit 0; touched paths include 2024.1 resources and exclude 2022.1/2023.1/global semantic fallback.
    Evidence: .sisyphus/evidence/task-2024-4-cross-version.txt

  Scenario: Default remains 2022.1
    Tool: Bash
    Steps: Run the default dispatcher test in `test_2024_cross_version_audit.py`.
    Expected: Default dry-run returns version `2022.1`; explicit 2024 dry-run returns `2024.1`.
    Evidence: .sisyphus/evidence/task-2024-4-default.txt
  ```

  **Commit**: YES | Message: `test(wwise): isolate 2024 version resources` | Files: `tests/unit/test_2024_cross_version_audit.py`

- [x] 5. Create 2024 semantic references and NotebookLM source notes

  **What to do**: Use NotebookLM active library `wwise-2024.1-docs` to ground semantic builder families `query`, `object-mutation`, `property-reference`, `import`, `soundbank`, and `switchcontainer`. Create `references/semantic/2024.1/*.md`, `references/semantic/2024.1/semantic-builder-notebooklm-gate.md`, and `resources/semantic/2024.1/source_notes.json` with version target, notebook id, required fields, source URLs, and gate evidence path.
  **Must NOT do**: Do not let runtime builders call NotebookLM; do not cite 2022/2023 notebooks as 2024 evidence.

  **Recommended Agent Profile**:
  - Category: `writing` - Source-grounded documentation and JSON evidence.
  - Skills: [`notebooklm`] - Query active `wwise-2024.1-docs` library.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: Tasks 6, 7, 11, 13 | Blocked By: Task 3

  **References**:
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:134-157` - Versioned source-note assertions.
  - Pattern: `references/semantic/2023.1/semantic-builder-protocol.md` - Versioned reference style.
  - Pattern: `resources/semantic/2023.1/source_notes.json` - Source-note schema.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2024_reference_layout.py tests/unit/test_2024_cross_version_audit.py -q` exits 0.
  - [ ] Source notes use `wwise-2024.1-docs` and version `2024.1` only.
  - [ ] No `wwise-2022.1-docs` or `wwise-2023.1-docs` appears as 2024 proof.

  **QA Scenarios**:
  ```
  Scenario: NotebookLM gate evidence exists
    Tool: Bash
    Steps: Parse `resources/semantic/2024.1/source_notes.json` and referenced gate evidence path.
    Expected: All notes cite `wwise-2024.1-docs` and `references/semantic/2024.1/`.
    Evidence: .sisyphus/evidence/task-2024-5-notebooklm-gate.txt

  Scenario: Runtime remains local-only
    Tool: Bash
    Steps: Run source-note/layout tests.
    Expected: Runtime source-note checks read local JSON/Markdown only; no NotebookLM runtime dependency.
    Evidence: .sisyphus/evidence/task-2024-5-runtime-local.txt
  ```

  **Commit**: YES | Message: `docs(wwise): ground 2024 semantic sources` | Files: `references/semantic/2024.1/*.md`, `resources/semantic/2024.1/source_notes.json`, `tests/unit/test_2024_reference_layout.py`

- [x] 6. Build 2024 parity coverage, policy, matrix, and deferred resources

  **What to do**: Generate `resources/coverage/2024.1/api-coverage.json`, `live-coverage-matrix.json`, `phase2-coverage-summary.json`, `phase21-uri-policy.json`, and `resources/deferred/2024.1.json` from the 2024 manifest and source notes. Start with conservative statuses: manifest-only entries are not behavioral; risky families excluded; no live/sandbox promotion until Tasks 8/10 create fresh 2024 evidence.
  **Must NOT do**: Do not copy 2023 counts or evidence as 2024 proof. Do not promote risky families by default.

  **Recommended Agent Profile**:
  - Category: `deep` - Cross-resource generated metadata and policy reconciliation.
  - Skills: [] - No specialized skill required.
  - Omitted: [`playwright`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: Tasks 7, 8, 10, 11, 13 | Blocked By: Tasks 3, 5

  **References**:
  - Pattern: `tests/unit/test_2023_api_resource_coverage.py:57-153` - Coverage metadata/status policy.
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:159-274` - Coverage/matrix/summary/policy/deferred reconciliation.
  - Pattern: `resources/coverage/2023.1/api-coverage.json` - 2023 resource shape only, not counts.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2024_api_resource_coverage.py tests/unit/test_2024_deferred_registry.py tests/unit/test_2024_live_coverage_matrix.py -q` exits 0.
  - [ ] Sum of 2024 parity buckets equals discovered 2024 reflected API count.
  - [ ] Deferred registry exactly matches coverage entries with `deferred` or `excluded` statuses.

  **QA Scenarios**:
  ```
  Scenario: 2024 resources reconcile
    Tool: Bash
    Steps: Run 2024 coverage/deferred/matrix unit tests.
    Expected: Exit 0; all reflected 2024 APIs classified exactly once.
    Evidence: .sisyphus/evidence/task-2024-6-coverage-baseline.txt

  Scenario: Risky families not promoted
    Tool: Bash
    Steps: Run risky-family assertions in `test_2024_api_resource_coverage.py`.
    Expected: profiler/transport/soundengine/UI/CLI/remote/debug entries are excluded/deferred and behavioral counts remain false.
    Evidence: .sisyphus/evidence/task-2024-6-risky-policy.txt
  ```

  **Commit**: YES | Message: `test(coverage): classify 2024 parity resources` | Files: `resources/coverage/2024.1/*.json`, `resources/deferred/2024.1.json`, `tests/unit/test_2024_*.py`

- [x] 7. Add 2024 parity audit and no-overclaim unit tests

  **What to do**: Add focused audits that lock discovered 2024 reflected counts, no fallback, source-note versioning, coverage/matrix/summary/deferred reconciliation, approved evidence roots, and docs/eval claim limits. Tests must permit future evidence-backed promotions but reject manifest-only live/sandbox claims.
  **Must NOT do**: Do not hardcode 2023 counts for 2024; derive expected totals from 2024 manifest/resources.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Cross-resource invariant tests.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: YES | Wave 2 | Blocks: Tasks 11, 13 | Blocked By: Tasks 4, 6

  **References**:
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:159-274` - Full reconciliation audit.
  - Pattern: `tests/unit/test_2023_docs_contract.py:21-112` - No-overclaim contract.
  - Pattern: `tests/unit/test_2023_live_coverage_matrix.py` - Live matrix invariants.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2024_cross_version_audit.py tests/unit/test_2024_docs_contract.py tests/unit/test_2024_live_coverage_matrix.py -q` exits 0.
  - [ ] Tests fail if explicit 2024 resources read 2022/2023 fallback paths.
  - [ ] Tests fail if docs claim all 2024.1 APIs are live-tested or full behavior-supported.

  **QA Scenarios**:
  ```
  Scenario: Audit suite validates parity scale
    Tool: Bash
    Steps: Run 2024 cross-version/docs/live-matrix audits.
    Expected: Exit 0; derived counts reconcile and no-overclaim phrases are absent.
    Evidence: .sisyphus/evidence/task-2024-7-audit-parity.txt

  Scenario: Manifest-only promotion rejected
    Tool: Bash
    Steps: Run evidence-root assertions in the 2024 audit tests.
    Expected: Any live/sandbox promotion must reference `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/` or `resources/waql/2024.1/`.
    Evidence: .sisyphus/evidence/task-2024-7-manifest-only-guard.txt
  ```

  **Commit**: YES | Message: `test(wwise): enforce 2024 parity audits` | Files: `tests/unit/test_2024_*.py`

- [x] 8. Add 2024 read-only live smoke and WAQL matrix evidence

  **What to do**: Port 2023 live prerequisite/reflection/WAQL read-only tests to 2024. Use sandbox copy launch, no mutation, source hash/mtime invariance, and per-case evidence under `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/live-read-only/`. Create `resources/waql/2024.1/object-get-live-matrix.json` from 2024 reflection and promote only `ak.wwise.core.object.get` if all cases pass.
  **Must NOT do**: Do not run against installed SampleProject directly; do not reuse 2023 evidence paths as 2024 proof.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Live Wwise sandbox evidence and generated resources.
  - Skills: [] - No specialized skill required.
  - Omitted: [`playwright`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: Tasks 10, 13 | Blocked By: Tasks 1, 2, 3, 6

  **References**:
  - Pattern: `tests/live/test_2023_waql_live_matrix.py:31-87` - Sandbox read-only setup and immutability.
  - Pattern: `tests/live/test_2023_waql_live_matrix.py:97-205` - Read-only WAQL guards and result assertions.
  - Pattern: `tests/live/test_2023_live_prerequisites.py` - Exact live prerequisite gate.

  **Acceptance Criteria**:
  - [ ] Exact 2024 live command exits 0 for targeted 2024 live tests.
  - [ ] `resources/waql/2024.1/object-get-live-matrix.json` exists and references only 2024 evidence.
  - [ ] Source project hash/mtime remains unchanged and sandbox copy is cleaned.

  **QA Scenarios**:
  ```
  Scenario: Read-only live WAQL passes
    Tool: Bash
    Steps: Run `WWISE_VERSION=2024.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" WWISE_LIVE=1 python -m pytest tests/live/test_2024_live_prerequisites.py tests/live/test_2024_reflection_inventory.py tests/live/test_2024_waql_live_matrix.py -q`.
    Expected: Exit 0; live evidence JSON written under 2024 evidence root.
    Evidence: .sisyphus/evidence/task-2024-8-live-read-only.txt

  Scenario: Mutation guard blocks unsafe WAQL
    Tool: Bash
    Steps: Run 2024 WAQL mutation guard unit tests.
    Expected: Mutating WAQL tokens are rejected before live execution.
    Evidence: .sisyphus/evidence/task-2024-8-read-only-guard.txt
  ```

  **Commit**: YES | Message: `test(live): add 2024 read-only parity evidence` | Files: `tests/live/test_2024_*.py`, `tests/unit/test_2024_waql_mutation_guard.py`, `resources/waql/2024.1/*.json`, `resources/coverage/2024.1/*.json`, `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/live-read-only/*`

- [x] 9. Add 2024 destructive sandbox runtime and fail-closed tests

  **What to do**: Add `wwise_waapi/destructive_2024_sandbox.py` by copying the 2023 pattern with 2024 constants, lock root, stale-sandbox cleanup, exact path checks, source immutability checks, and sandbox-copy proof. Add fail-closed tests for missing gates, wrong version, wrong paths, installed SampleProject target, `tests/_org/2024.1` target, and unsafe sandbox root.
  **Must NOT do**: Do not generalize 2023/2024 runtime broadly unless required by failing tests.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Destructive safety gate implementation.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: Task 10 | Blocked By: Tasks 1, 2

  **References**:
  - Pattern: `wwise_waapi/destructive_2023_sandbox.py:58-97` - Runtime lifecycle.
  - Pattern: `wwise_waapi/destructive_2023_sandbox.py:169-209` - Exact prerequisite and sandbox-copy proof.
  - Pattern: `tests/unit/test_2023_destructive_safety.py` - Negative-path safety tests.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2024_destructive_safety.py -q` exits 0.
  - [ ] Missing gates fail before sandbox preparation/WwiseConsole launch.
  - [ ] Installed SampleProject and `tests/_org/2024.1` cannot be active destructive projects.

  **QA Scenarios**:
  ```
  Scenario: Destructive gates fail closed
    Tool: Bash
    Steps: Run 2024 destructive safety unit tests.
    Expected: Exit 0; missing gates stop before sandbox preparation or launch.
    Evidence: .sisyphus/evidence/task-2024-9-fail-closed.txt

  Scenario: Immutable targets rejected
    Tool: Bash
    Steps: Run installed SampleProject and `tests/_org/2024.1` target rejection tests.
    Expected: LiveEnvironmentError/SandboxFixtureError includes immutable source path fragments.
    Evidence: .sisyphus/evidence/task-2024-9-immutable-targets.txt
  ```

  **Commit**: YES | Message: `test(destructive): harden 2024 sandbox gates` | Files: `wwise_waapi/destructive_2024_sandbox.py`, `tests/unit/test_2024_destructive_safety.py`

- [x] 10. Add 2024 sandbox-mutating destructive evidence and promotion updates

  **What to do**: Port safe 2023 destructive cases to 2024 for object create/set/delete, undo begin/end/undo, audio.import, soundbank.setInclusions, and switchContainer assignment add/remove. Write per-case evidence under `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/destructive/`. Promote only APIs with passing 2024 destructive evidence to `sandbox-mutating-tested` in 2024 coverage/matrix/summary/policy resources.
  **Must NOT do**: Do not promote readback-only helper APIs; do not promote risky families.

  **Recommended Agent Profile**:
  - Category: `deep` - Live destructive evidence plus resource reconciliation.
  - Skills: [] - No specialized skill required.
  - Omitted: [`playwright`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: Tasks 11, 13 | Blocked By: Tasks 6, 8, 9

  **References**:
  - Pattern: `tests/destructive/test_2023_project_mutation_sandbox.py` - Object and undo mutation evidence.
  - Pattern: `tests/destructive/test_2023_soundbank_audio_sandbox.py` - Audio/soundbank evidence.
  - Pattern: `tests/destructive/test_2023_switchcontainer_assignment_sandbox.py` - SwitchContainer evidence.
  - Pattern: `.sisyphus/notepads/wwise-2023-test-parity/learnings.md:17-20` - Promotion and cleanup gotchas.

  **Acceptance Criteria**:
  - [ ] Exact 2024 destructive command exits 0 for targeted 2024 destructive tests.
  - [ ] Per-case destructive evidence exists under the 2024 evidence root.
  - [ ] Coverage resources promote only passing mutating APIs and keep readback helpers unpromoted.

  **QA Scenarios**:
  ```
  Scenario: Sandbox-mutating evidence passes
    Tool: Bash
    Steps: Run `WWISE_VERSION=2024.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 python -m pytest tests/destructive/test_2024_project_mutation_sandbox.py tests/destructive/test_2024_soundbank_audio_sandbox.py tests/destructive/test_2024_switchcontainer_assignment_sandbox.py -q`.
    Expected: Exit 0; source SampleProject unchanged and runtime root cleaned.
    Evidence: .sisyphus/evidence/task-2024-10-destructive-sandbox.txt

  Scenario: No accidental promotion
    Tool: Bash
    Steps: Run 2024 coverage/deferred/matrix audits after promotions.
    Expected: Readback helpers and risky families remain non-behavioral unless explicitly promoted by fresh evidence.
    Evidence: .sisyphus/evidence/task-2024-10-no-accidental-promotion.txt
  ```

  **Commit**: YES | Message: `test(destructive): add 2024 sandbox parity evidence` | Files: `tests/destructive/test_2024_*.py`, `resources/coverage/2024.1/*.json`, `resources/deferred/2024.1.json`, `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/destructive/*`

- [x] 11. Produce 2024 docs, evals, and review packet without overclaims

  **What to do**: Update `SKILL.md`, `references/long-run-runbook.md`, `references/eval-review-workflow.md`, `references/phase2-user-review-packet.md`, and `evals/evals.json` only where 2024.1 planning/support claims need exact paths and no-overclaim wording. Create `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/parity-review-packet.md` with promoted evidence, deferred/excluded policy, exact commands, source immutability, Windows caveat, and known non-goals.
  **Must NOT do**: Do not claim full 2024.1 support or all APIs live-tested.

  **Recommended Agent Profile**:
  - Category: `writing` - Precise technical docs.
  - Skills: [] - No specialized skill required.
  - Omitted: [`humanizer-zh`] - English repo docs.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: Task 13 | Blocked By: Tasks 5, 6, 7, 10

  **References**:
  - Pattern: `tests/unit/test_2023_docs_contract.py:21-112` - Exact paths and forbidden claims.
  - Pattern: `.sisyphus/evidence/wwise-2023-test-parity/parity-review-packet.md` - Review packet structure.
  - Pattern: `references/wwise-version-upgrade-2023-first.md:122-142` - Exact 2024 commands.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2024_docs_contract.py -q` exits 0.
  - [ ] Review packet includes `Promoted Evidence`, `Deferred/Excluded`, `Commands Run`, `Source Immutability`, `Windows Caveat`, `Known Non-Goals`.
  - [ ] Docs say Windows validation is non-blocking evidence/caveat, not a hard gate.

  **QA Scenarios**:
  ```
  Scenario: Docs avoid full-coverage overclaims
    Tool: Bash
    Steps: Run 2024 docs contract tests.
    Expected: Forbidden positive claims are absent; exact 2024 paths are present.
    Evidence: .sisyphus/evidence/task-2024-11-docs-contract.txt

  Scenario: Review packet complete
    Tool: Bash
    Steps: Parse the 2024 parity review packet headings.
    Expected: Required six headings are present in exact order.
    Evidence: .sisyphus/evidence/task-2024-11-review-packet.txt
  ```

  **Commit**: YES | Message: `docs(wwise): document 2024 parity evidence` | Files: `SKILL.md`, `references/*.md`, `evals/evals.json`, `tests/unit/test_2024_docs_contract.py`, `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/parity-review-packet.md`

- [x] 12. Verify default Wwise-free behavior and 2024 explicit opt-in gates

  **What to do**: Prove default tests do not require Wwise and default dispatch remains 2022.1. Prove 2024 live/destructive tests skip/fail safely unless explicitly opted in. Record command outputs.
  **Must NOT do**: Do not set repo-global default `WWISE_VERSION=2024.1`.

  **Recommended Agent Profile**:
  - Category: `quick` - Command verification and small gate adjustments only.
  - Skills: [] - No specialized skill required.
  - Omitted: [`git-master`] - Only use during commit.

  **Parallelization**: Can Parallel: YES | Wave 3 | Blocks: Task 13 | Blocked By: Tasks 1, 4, 9

  **References**:
  - Pattern: `tests/conftest.py` - Default live/destructive skip gates.
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:61-95` - Default vs explicit dispatch.
  - Pattern: `tests/destructive/test_2023_project_mutation_sandbox.py` - Module-level destructive gate.

  **Acceptance Criteria**:
  - [ ] `env -u WWISE_LIVE -u WWISE_DESTRUCTIVE python -m pytest -q` exits 0.
  - [ ] `env -u WWISE_LIVE -u WWISE_DESTRUCTIVE WWISE_VERSION=2024.1 python -m pytest tests/destructive/test_2024_project_mutation_sandbox.py -q` skips/fails safely before WwiseConsole launch.
  - [ ] `python -m pytest tests/unit/test_2024_cross_version_audit.py -q` exits 0.

  **QA Scenarios**:
  ```
  Scenario: Default suite Wwise-free
    Tool: Bash
    Steps: Run `env -u WWISE_LIVE -u WWISE_DESTRUCTIVE python -m pytest -q`.
    Expected: Exit 0; live/destructive tests skip by gates.
    Evidence: .sisyphus/evidence/task-2024-12-default-suite.txt

  Scenario: 2024 destructive explicit opt-in holds
    Tool: Bash
    Steps: Run destructive 2024 module with only `WWISE_VERSION=2024.1`.
    Expected: Safe skip/failure before runtime setup and no project mutation.
    Evidence: .sisyphus/evidence/task-2024-12-destructive-skip.txt
  ```

  **Commit**: YES | Message: `test(wwise): verify 2024 opt-in gates` | Files: `.sisyphus/evidence/task-2024-12-*.txt`, tests only if gate fixes needed

- [ ] 13. Final 2024 resource, evidence, and artifact reconciliation

  **What to do**: Reconcile all 2024 resources and evidence after Tasks 1-12. Confirm no orphan APIs, no stale 2023/2022 paths in explicit 2024 resources, no missing evidence files for promoted entries, no risky accidental promotions, no docs contradictions, and no runtime artifacts staged/tracked. Update 2024 parity review packet with final command results and counts.
  **Must NOT do**: Do not silently drop APIs to make counts pass; do not run 2025 work.

  **Recommended Agent Profile**:
  - Category: `deep` - End-to-end reconciliation.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 4 | Blocks: F1-F4 | Blocked By: Tasks 7, 8, 10, 11, 12

  **References**:
  - Pattern: `tests/unit/test_2023_cross_version_audit.py:159-274` - Full resource reconciliation.
  - Pattern: `.sisyphus/evidence/task-10-final-reconciliation.txt` - 2023 final reconciliation evidence model.
  - Pattern: `.sisyphus/notepads/wwise-2023-test-parity/learnings.md:32-34` - Generated evidence rewrite and staging gotchas.

  **Acceptance Criteria**:
  - [ ] Focused 2024 unit audit command exits 0.
  - [ ] Exact 2024 live command exits 0 or records prerequisite blocker with no mutation.
  - [ ] Exact 2024 destructive command exits 0 or records fail-closed blocker with no mutation.
  - [ ] `python -m pytest -q` exits 0.
  - [ ] `git status --short -- .sisyphus/runtime` and `git ls-files .sisyphus/runtime` produce no tracked/staged runtime artifacts.

  **QA Scenarios**:
  ```
  Scenario: Full 2024 parity verification passes
    Tool: Bash
    Steps: Run focused unit audit, exact 2024 live command, exact 2024 destructive command, and default full pytest.
    Expected: All commands exit 0 or document safe prerequisite blockers; review packet updated with final counts/results.
    Evidence: .sisyphus/evidence/task-2024-13-final-reconciliation.txt

  Scenario: No runtime/generated artifact leakage
    Tool: Bash
    Steps: Run `git status --short`, `git status --short -- .sisyphus/runtime`, and `git ls-files .sisyphus/runtime`.
    Expected: No runtime sandbox, generated banks, logs, or copied SampleProject artifacts staged/tracked.
    Evidence: .sisyphus/evidence/task-2024-13-no-runtime-artifacts.txt
  ```

  **Commit**: YES | Message: `test(wwise): reconcile 2024 parity evidence` | Files: `resources/coverage/2024.1/*.json`, `resources/deferred/2024.1.json`, `resources/waql/2024.1/*.json`, `tests/unit/test_2024_*.py`, `tests/live/test_2024_*.py`, `tests/destructive/test_2024_*.py`, `references/*.md`, `evals/evals.json`, `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/*`

## Final Verification Wave (MANDATORY — after ALL implementation tasks)
> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.
- [ ] F1. Plan Compliance Audit — oracle
- [ ] F2. Code Quality Review — unspecified-high
- [ ] F3. Real Manual QA — unspecified-high (+ Bash/live/destructive commands; Playwright not required because no UI)
- [ ] F4. Scope Fidelity Check — deep

## Commit Strategy
- Commit after each task when its acceptance commands pass.
- Use exact commit messages listed per task.
- Do not push unless explicitly requested.
- Force-add intended `.sisyphus/evidence/` and `.sisyphus/plans/` files because `.sisyphus/` is ignored.
- Never stage `.sisyphus/runtime`, copied sandbox projects, Wwise logs, generated banks, generated audio, `__pycache__`, `.coverage`, or unrelated evidence from other plans.

## Success Criteria
- 2024.1 reflected API count is discovered and every reflected API is accounted for exactly once.
- 2024.1 resources are version-isolated and fail closed with no 2022/2023/global fallback.
- 2024.1 behavioral/live/destructive counts are backed only by fresh 2024.1 evidence.
- Risky families remain deferred/excluded unless explicitly and safely evidenced.
- Default pytest remains Wwise-free and 2022.1-default.
- Review packet states Windows is non-blocking evidence/caveat, not a hard gate.
