# Wwise 2025.1.7 WAAPI Integration and Test Coverage

## TL;DR
> **Summary**: Add Wwise 2025.1 as a version-isolated, fail-closed WAAPI lane and include parity-scale test coverage in the same execution plan. Use the completed 2024.1 lane as the closest template while discovering 2025.1 counts and 2025-only APIs from fresh live reflection and NotebookLM-grounded semantics.
> **Deliverables**: 2025.1 version/env support; immutable fixture; manifest/semantic/coverage/deferred/WAQL resources; 2025-only API classification; live/destructive evidence; docs/evals review packet; final reconciliation.
> **Effort**: XL
> **Parallel**: YES - 5 waves
> **Critical Path**: Task 1 → Task 2 → Task 3 → Tasks 5-8 → Tasks 9-11 → Task 14 → Final Verification Wave

## Context
### Original Request
- User asked Prometheus to plan Wwise 2025 WAAPI skill support using `references/wwise-version-upgrade-2023-first.md`.
- User said NotebookLM is ready; use `wwise-2025.1-docs` for documentation questions.
- User wants the 2025 work to match the 2024 approach: one large plan that completes WAAPI integration and test coverage together.
- User wants test scale comparable to 2024.

### Confirmed 2025.1.7 Inputs
- Version key for resources/env/tests: `2025.1`.
- Installed build/path suffix: `2025.1.7.9143`.
- WwiseConsole: `/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh`.
- SampleProject: `/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj`.
- NotebookLM active library: `wwise-2025.1-docs`.

### Interview Summary
- Test strategy: 2024 practical model — tests-after with targeted TDD-style guard tests before risky shared-code changes.
- Coverage goal: align with 2024 classification and behavior families, but expect many 2025-added WAAPI interfaces; executor should semantically understand and safely attempt coverage for new interfaces.
- Promotion rule: 2024 evidence is precedent only, never proof for 2025.

### Research Summary
- 2024 plan pattern: 13 implementation tasks plus final review wave covering version contracts, fixture, live reflection, cross-version audit, NotebookLM source notes, coverage/deferred resources, live read-only evidence, destructive sandbox safety/evidence, docs/evals, opt-in gates, final reconciliation.
- Test infrastructure exists: `pyproject.toml:1-17`, `tests/conftest.py:15-32`, 2024 unit/live/destructive test suites, Python-native JSON validation fallback, local coverage configuration but no dedicated CI workflow.
- Core code anchors: `wwise_waapi/versions.py:8-38`, `wwise_waapi/live_environment.py:19-29,91-109,112-203,206-266`, `wwise_waapi/sandbox_fixture.py:33-37,106-198,201-245,266-359`, `wwise_waapi/manifest.py:1-18,156-218,221-254`, `wwise_waapi/deferred_registry.py:1-27,89-170,174-240`.
- 2025 placeholders: planning-only 2025.1 inputs in `references/wwise-version-upgrade-2023-first.md:55-105,156-186` and empty `resources/manifest/2025/.gitkeep` only.
- 2025 docs risks to verify: hierarchy naming changes (`Containers`, `Busses`, `Devices`, `Property Container`), `ak.wwise.core.object.structureChanged`, `ak.wwise.core.object.getPropertyNames` deprecation/replacement, `ak.wwise.core.object.set` slot-wrapped list data, profiler/legacy API assumptions.

### Metis Review (gaps addressed)
- Added a dedicated 2025-only discovery/classification task.
- Added formal promotion/defer rules for new and existing APIs.
- Required 2024 baseline counts to be generated from repo during execution, not from memory.
- Required discrepancy logging when reflection, docs, and live behavior disagree.
- Required 2024 regression tests after shared-code changes.
- Required explicit fallback behavior if NotebookLM is unavailable: stop docs-dependent promotion and record blocker; do not guess.

## Work Objectives
### Core Objective
Support Wwise 2025.1.7 WAAPI resources and tests as an explicit opt-in version lane, with 2024-scale coverage governance and fresh 2025 evidence included in the first execution plan.

### Deliverables
- `resources/manifest/2025.1/` split manifest resources.
- `references/semantic/2025.1/` and `resources/semantic/2025.1/source_notes.json` grounded by `wwise-2025.1-docs`.
- `resources/coverage/2025.1/{api-coverage.json,live-coverage-matrix.json,phase2-coverage-summary.json,phase21-uri-policy.json}`.
- `resources/deferred/2025.1.json` and `resources/waql/2025.1/`.
- `tests/_org/2025.1/` immutable fixture metadata and tests.
- `tests/unit/test_2025_1_*.py`, `tests/live/test_2025_1_*.py`, and `tests/destructive/test_2025_1_*.py`.
- Evidence under `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/` plus task-specific `.sisyphus/evidence/task-2025-*.txt`.
- 2025 docs/evals/review packet with no full-support overclaims.

### Definition of Done (verifiable conditions with commands)
- `python -m pytest -q` exits 0 without launching WwiseConsole.
- `python -m pytest tests/unit/test_2025_1_*.py -q` exits 0.
- Exact 2025.1 live command exits 0 or records safe prerequisite blocker before mutation.
- Exact 2025.1 destructive command exits 0 for planned copied-sandbox cases or records fail-closed blocker before mutation.
- Focused 2025 reconciliation command exits 0 and reconciles reflected APIs, coverage entries, matrix entries, policy assignments, deferred registry, source notes, and docs/evals.
- 2024 regression command exits 0 after shared-code changes.
- `git status --short -- .sisyphus/runtime` and `git ls-files .sisyphus/runtime` produce no tracked/staged runtime artifacts.

### Must Have
- Default dispatcher/runtime remains `2022.1` unless `WWISE_VERSION=2025.1` or explicit `version="2025.1"` is supplied.
- `2025.1` never falls back to 2022.1, 2023.1, 2024.1, `resources/manifest/2025`, or global unversioned semantic docs.
- Reflection owns API inventory; NotebookLM/official docs own semantic/source-note grounding.
- Every promoted 2025 URI must be present in 2025 reflection, grounded by 2025 docs, tested by executable 2025 live/destructive evidence, and referenced in 2025 reconciliation resources.
- 2025-only APIs must be classified explicitly: promote only when safe and evidenced; otherwise defer with reason.

### Must NOT Have
- No bare `2025` alias.
- No reuse of 2022/2023/2024 evidence as 2025 proof.
- No mutation of installed SampleProject or `tests/_org/2025.1`.
- No speculative support for undocumented or unverified WAAPI interfaces.
- No broad dispatcher/builder architecture rewrite unless fresh 2025 evidence proves it necessary.
- No CI workflow, packaging overhaul, or unrelated refactor.
- No claims that all 2025.1 APIs are live-tested or fully behavior-tested.

## Verification Strategy
> ZERO HUMAN INTERVENTION - all verification is agent-executed.
- Test decision: 2024 practical model — tests-after with targeted TDD-style guard tests before risky shared-code changes.
- QA policy: Every task has agent-executed happy and failure scenarios.
- Evidence root: `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/` plus task-specific `.sisyphus/evidence/task-2025-*.txt`.
- Live command path must use exact 2025.1.7 WwiseConsole and SampleProject paths above.
- Destructive command must use copied sandbox root `.sisyphus/runtime/wwise-waapi-sandboxes` and `WWISE_DESTRUCTIVE=1`.
- JSON validation may use Python parsing/tests because Biome may be unavailable in this environment.

## Execution Strategy
### Parallel Execution Waves
> Target: 5-8 tasks per wave. Shared dependencies are Wave 1 for maximum parallelism.

Wave 1: Tasks 1-4 — version lane, fixture, manifest reflection, isolation audits.
Wave 2: Tasks 5-8 — NotebookLM source notes, 2025-only classification, coverage/deferred baseline, parity audits.
Wave 3: Tasks 9-12 — live read-only tests, destructive safety, destructive evidence, docs/evals packet.
Wave 4: Tasks 13-14 — opt-in/regression gates and final reconciliation.
Wave 5: F1-F4 final review agents.

### Dependency Matrix (full, all tasks)
- T1 blocks T3, T4, T9, T10, T13.
- T2 blocks T3, T9, T10, T11.
- T3 blocks T5, T6, T7, T8, T9, T14.
- T5 blocks T6, T7, T8, T12, T14.
- T6 blocks T7, T8, T9, T11, T14.
- T7 blocks T8, T12, T14.
- T8 blocks T9, T11, T14.
- T10 blocks T11, T13.
- T9 and T11 block promotion updates and T14.
- T12 and T13 block T14.
- T14 blocks F1-F4.

### Agent Dispatch Summary (wave → task count → categories)
- Wave 1 → 4 tasks → unspecified-high/deep.
- Wave 2 → 4 tasks → writing/unspecified-high/deep.
- Wave 3 → 4 tasks → unspecified-high/writing.
- Wave 4 → 2 tasks → quick/deep.
- Wave 5 → 4 final reviewers → oracle/unspecified-high/unspecified-high/deep.

## TODOs
> Implementation + Test = ONE task. Never separate.
> EVERY task MUST have: Agent Profile + Parallelization + QA Scenarios.

- [x] 1. Add fail-closed 2025.1 version and live environment contracts

  **What to do**: Add `WWISE_2025_1_VERSION_KEY="2025.1"`, `WWISE_2025_1_BUILD="2025.1.7.9143"`, and a frozen `WwiseVersionContract` in `wwise_waapi/versions.py`. Add exact 2025 WwiseConsole/SampleProject constants, `LIVE_VERSION_PATHS` entry with `require_exact_paths=True`, and installed SampleProject root immutability in `wwise_waapi/live_environment.py`. Add `tests/unit/test_2025_1_version_contract.py` and `tests/unit/test_2025_1_live_environment_contract.py` mirroring 2024 tests.
  **Must NOT do**: Do not change `DEFAULT_WWISE_VERSION` from `2022.1`. Do not make `2025` an alias for `2025.1`.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Cross-cutting version/env safety code.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: Tasks 3, 4, 9, 10, 13 | Blocked By: none

  **References**:
  - Pattern: `wwise_waapi/versions.py:8-38` - Existing version key/build contract and fail-closed set.
  - Pattern: `wwise_waapi/live_environment.py:19-29,91-109,112-203,206-266` - Exact path contracts, fail-fast guards, immutable-source checks.
  - Test: `tests/unit/test_2024_version_contract.py:11-56` - Default remains 2022.1 and bare alias rejection.
  - Test: `tests/unit/test_2024_live_environment_contract.py` - Port exact-path/no-fallback/destructive-target assertions.
  - Input: `references/wwise-version-upgrade-2023-first.md:55-73` - Exact 2025 paths and NotebookLM id.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2025_1_version_contract.py tests/unit/test_2025_1_live_environment_contract.py -q` exits 0.
  - [ ] `DEFAULT_WWISE_VERSION` remains `2022.1`.
  - [ ] `WWISE_VERSION=2025.1` live prereqs require exact 2025.1.7 paths and never fallback to 2022.1/2023.1/2024.1/bare 2025.

  **QA Scenarios**:
  ```
  Scenario: Exact 2025 env accepted
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2025_1_version_contract.py tests/unit/test_2025_1_live_environment_contract.py -q`.
    Expected: Exit 0; tests assert exact console/sample paths and version key.
    Evidence: .sisyphus/evidence/task-2025-1-version-env.txt

  Scenario: Bare alias and wrong path fail closed
    Tool: Bash
    Steps: Run the new tests that monkeypatch `WWISE_VERSION=2025` and wrong console/sample paths.
    Expected: Fail-closed error mentions exact `2025.1` and exact 2025.1.7 paths; no fallback dispatch/resource read occurs.
    Evidence: .sisyphus/evidence/task-2025-1-fail-closed.txt
  ```

  **Commit**: YES | Message: `feat(wwise): add 2025 version contracts` | Files: `wwise_waapi/versions.py`, `wwise_waapi/live_environment.py`, `tests/unit/test_2025_1_*.py`

- [x] 2. Create immutable 2025.1 fixture source from installed SampleProject

  **What to do**: Copy only `/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj` and authored `.wwu` files into `tests/_org/2025.1/`. Generate `README.md`, `fixture-metadata.json`, and `fixture-manifest.json` matching the 2024 fixture conventions. Exclude generated banks, logs, caches, audio outputs, runtime files, auth state, and platform-generated outputs.
  **Must NOT do**: Do not mutate or commit the installed SampleProject. Do not copy generated artifacts.

  **Recommended Agent Profile**:
  - Category: `deep` - Requires filesystem provenance and artifact exclusion.
  - Skills: [] - No specialized skill required.
  - Omitted: [`git-master`] - Commit happens after verification only.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: Tasks 3, 9, 10, 11 | Blocked By: Task 1

  **References**:
  - Pattern: `tests/unit/test_2024_fixture_inventory.py:41-165` - 2024 immutable fixture inventory and generated-artifact exclusions.
  - Pattern: `tests/unit/test_2023_fixture_source.py:27-136` - Manifest hash and destructive rejection.
  - Pattern: `wwise_waapi/sandbox_fixture.py:106-198,266-359` - Source copy and immutability proof.
  - Input: `references/wwise-version-upgrade-2023-first.md:61-65,178` - Exact 2025 SampleProject path and immutability rule.

  **Acceptance Criteria**:
  - [ ] `tests/_org/2025.1/SampleProject.wproj` exists.
  - [ ] `python -m pytest tests/unit/test_2025_1_fixture_inventory.py -q` exits 0.
  - [ ] Fixture manifest contains only `.wproj`, `.wwu`, README, and approved metadata files.

  **QA Scenarios**:
  ```
  Scenario: Fixture provenance recorded
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2025_1_fixture_inventory.py -q`.
    Expected: Metadata references build `2025.1.7.9143` and the exact installed SampleProject path.
    Evidence: .sisyphus/evidence/task-2025-2-fixture.txt

  Scenario: Runtime artifacts excluded
    Tool: Bash
    Steps: Run the fixture inventory test and parse `tests/_org/2025.1/fixture-manifest.json`.
    Expected: No `.akd`, `.bnk`, `.wem`, `.log`, `GeneratedSoundBanks`, `Logs`, caches, auth state, or runtime sandbox paths.
    Evidence: .sisyphus/evidence/task-2025-2-no-runtime.txt
  ```

  **Commit**: YES | Message: `test(wwise): add 2025 fixture source` | Files: `tests/_org/2025.1/*`, `tests/unit/test_2025_1_fixture_inventory.py`

- [x] 3. Generate 2025.1 live reflection manifest resources and 2025-only inventory

  **What to do**: Use exact 2025 live env to reflect functions, topics, and schemas into `resources/manifest/2025.1/{manifest.json,functions.json,topics.json,schemas.json}`. Include build metadata `2025.1.7.9143`, scrubbed paths, source URIs, audit counts, schema failure count, and a derived `resources/manifest/2025.1/added-since-2024.1.json` comparing reflected 2025 functions/topics to 2024.1 resources. Accept discovered counts; do not normalize to 2024 counts.
  **Must NOT do**: Do not place payloads under `resources/manifest/2025/`. Do not reuse 2024 counts or 2024 schema proof.

  **Recommended Agent Profile**:
  - Category: `deep` - Live reflection and deterministic generated resources.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: Tasks 4, 5, 6, 7, 8, 9, 14 | Blocked By: Tasks 1, 2

  **References**:
  - Pattern: `wwise_waapi/manifest.py:156-218,221-254` - Reflection builder, deterministic JSON writer, versioned load.
  - Test: `tests/unit/test_2024_manifest_resources.py:52-131` - Provenance, counts, no fallback, path scrubbing.
  - Guard: `tests/unit/test_2024_cross_version_audit.py:145-157,216-397` - Existing placeholder/no-2025-payload guard.

  **Acceptance Criteria**:
  - [ ] `resources/manifest/2025.1/manifest.json` exists and reports `wwise_version_target == "2025.1"`.
  - [ ] `resources/manifest/2025.1/added-since-2024.1.json` exists and classifies new/removed/changed reflected APIs.
  - [ ] `python -m pytest tests/unit/test_2025_1_manifest_resources.py -q` exits 0.
  - [ ] Evidence records reflected function/topic/schema counts discovered from 2025.1.

  **QA Scenarios**:
  ```
  Scenario: Live reflection succeeds
    Tool: Bash
    Steps: Run the 2025.1 manifest generation command with exact console/sample paths and `WWISE_LIVE=1`.
    Expected: Exit 0; split manifest files written only under `resources/manifest/2025.1/`; counts recorded.
    Evidence: .sisyphus/evidence/task-2025-3-manifest-reflection.txt

  Scenario: 2025-only inventory is explicit
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2025_1_manifest_resources.py -q` and parse `added-since-2024.1.json`.
    Expected: New/removed/changed APIs are listed; no 2024 proof is treated as 2025 evidence.
    Evidence: .sisyphus/evidence/task-2025-3-added-inventory.txt
  ```

  **Commit**: YES | Message: `test(wwise): reflect 2025 manifest resources` | Files: `resources/manifest/2025.1/*.json`, `tests/unit/test_2025_1_manifest_resources.py`, `.sisyphus/evidence/task-2025-3-*.txt`

- [x] 4. Add 2025 cross-version isolation and default-dispatch audits

  **What to do**: Add `tests/unit/test_2025_1_cross_version_audit.py` and `tests/unit/test_2025_1_version_isolation.py`. Assert default remains 2022.1, explicit 2025.1 dry-run dispatch succeeds from 2025.1 manifest, explicit 2025.1 resource reads never touch 2022.1/2023.1/2024.1/bare 2025/global semantic references, and existing 2023/2024 tests still pass after shared-code changes.
  **Must NOT do**: Do not weaken 2023/2024 audits to make 2025 pass.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Version isolation across all existing lanes.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 1 | Blocks: Tasks 7, 8, 13, 14 | Blocked By: Tasks 1, 3

  **References**:
  - Pattern: `tests/unit/test_2024_cross_version_audit.py:72-397` - Full 2024 reconciliation and no-fallback guards.
  - Pattern: `tests/unit/test_2023_version_isolation.py:36-102` - Explicit version resource lookup without global fallback.
  - Pattern: `tests/unit/test_2024_version_contract.py:11-56` - Bare alias rejection and default dispatch.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2025_1_cross_version_audit.py tests/unit/test_2025_1_version_isolation.py -q` exits 0.
  - [ ] `python -m pytest tests/unit/test_2024_cross_version_audit.py tests/unit/test_2024_version_contract.py -q` exits 0.
  - [ ] Explicit `2025.1` reads reject 2022.1/2023.1/2024.1/bare 2025/global proof.

  **QA Scenarios**:
  ```
  Scenario: Explicit 2025 reads stay isolated
    Tool: Bash
    Steps: Run new 2025 cross-version and isolation tests.
    Expected: Exit 0; tests fail if any stale proof path or bare `resources/manifest/2025` payload is used.
    Evidence: .sisyphus/evidence/task-2025-4-isolation.txt

  Scenario: 2024 regression still passes
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2024_cross_version_audit.py tests/unit/test_2024_version_contract.py -q`.
    Expected: Exit 0; 2025 shared-code changes do not regress 2024 lane.
    Evidence: .sisyphus/evidence/task-2025-4-2024-regression.txt
  ```

  **Commit**: YES | Message: `test(wwise): isolate 2025 version resources` | Files: `tests/unit/test_2025_1_*.py`, shared version/resource code only if required

- [x] 5. Ground 2025.1 semantic source notes with NotebookLM

  **What to do**: Query active NotebookLM library `wwise-2025.1-docs` for 2025.1 source evidence. The query set must cover Wwise Authoring API Reference, Wwise Objects Reference, WAQL Reference, Command Identifiers, View Identifiers, Performance Monitor Counter Identifiers, and public-library endpoint/topic pages for each planned family. Create `references/semantic/2025.1/semantic-builder-notebooklm-gate.md`, family notes for `query`, `object-mutation`, `property-reference`, `import`, `soundbank`, `switchcontainer`, and `semantic-builder-protocol.md`. Create `resources/semantic/2025.1/source_notes.json`. Capture docs discrepancies in `references/semantic/2025.1/discrepancy-register.md`.
  **Must NOT do**: Do not let runtime builders call NotebookLM. Do not infer 2025 semantics from 2024 docs without 2025 evidence.

  **Recommended Agent Profile**:
  - Category: `writing` - Documentation/source evidence and structured notes.
  - Skills: [`notebooklm`] - Required for source-grounded 2025 docs queries.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: Tasks 6, 7, 8, 12, 14 | Blocked By: Task 3

  **References**:
  - Pattern: `references/semantic/2024.1/semantic-builder-notebooklm-gate.md:1-30` - Gate evidence shape.
  - Pattern: `references/semantic/2024.1/semantic-builder-protocol.md:1-42` - Required source-note sections.
  - Pattern: `references/semantic/2024.1/semantic-builder-query.md:1-54`, `semantic-builder-object-mutation.md:1-94`, `semantic-builder-property-reference.md:1-96`, `semantic-builder-import.md:1-70`, `semantic-builder-soundbank.md:1-83`, `semantic-builder-switchcontainer.md:1-68` - Family-note shapes.
  - Test: `tests/unit/test_2024_reference_layout.py:79-179` - Reference layout and local runtime-only behavior.

  **Acceptance Criteria**:
  - [ ] `references/semantic/2025.1/semantic-builder-notebooklm-gate.md` confirms notebook id `wwise-2025.1-docs` and version target `2025.1`.
  - [ ] `resources/semantic/2025.1/source_notes.json` exists and parses as JSON.
  - [ ] `python -m pytest tests/unit/test_2025_1_reference_layout.py -q` exits 0.
  - [ ] Gate/family notes include required fields, optional fields, return shape, destructive behavior, ambiguity constraints, unsupported cases, cited required fields, and official URL candidates or caveats.
  - [ ] Discrepancy register covers 2025 hierarchy naming, `object.structureChanged`, `object.getPropertyNames`, `object.set` slot-wrapped list data, and profiler/legacy assumptions.

  **QA Scenarios**:
  ```
  Scenario: NotebookLM gate is 2025-only
    Tool: Bash + NotebookLM
    Steps: Query `wwise-2025.1-docs`, write gate/family notes, run `python -m pytest tests/unit/test_2025_1_reference_layout.py -q`.
    Expected: Exit 0; tests reject 2022/2023/2024/global docs as 2025 source proof.
    Evidence: .sisyphus/evidence/task-2025-5-notebooklm-gate.txt

  Scenario: Missing docs fail closed
    Tool: Bash
    Steps: Run layout tests that simulate missing/wrong notebook id or absent required family fields.
    Expected: Exit 0 because tests assert docs-dependent promotion is blocked and discrepancy is recorded.
    Evidence: .sisyphus/evidence/task-2025-5-docs-fail-closed.txt
  ```

  **Commit**: YES | Message: `docs(wwise): ground 2025 semantic sources` | Files: `references/semantic/2025.1/*.md`, `resources/semantic/2025.1/source_notes.json`, `tests/unit/test_2025_1_reference_layout.py`, `.sisyphus/evidence/task-2025-5-*.txt`

- [x] 6. Classify 2025-only APIs and semantic deltas

  **What to do**: Build `resources/coverage/2025.1/added-api-classification.json` from `resources/manifest/2025.1/added-since-2024.1.json` plus 2025 source notes. Classify each 2025-only or changed API into existing 2024 families where semantics match, or explicit 2025-only family buckets. For each item choose one status: `candidate-live-read-only`, `candidate-sandbox-mutating`, `deferred`, or `excluded`. Defer by default on docs/reflection mismatch, unsafe state requirements, missing SampleProject fixture state, profiler/session requirements, or unsupported/unclear semantics.
  **Must NOT do**: Do not promote any 2025-only API to behavior-tested in this task.

  **Recommended Agent Profile**:
  - Category: `deep` - Requires semantic comparison and conservative classification.
  - Skills: [] - NotebookLM evidence is already local from Task 5.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: Tasks 7, 8, 9, 11, 14 | Blocked By: Tasks 3, 5

  **References**:
  - Pattern: `tests/unit/test_2024_live_coverage_matrix.py:36-175` - Status accounting and risky-family exclusions.
  - Pattern: `tests/unit/test_2024_deferred_registry.py:30-111` - Blocked entries and promoted URI exclusion.
  - Source: `references/semantic/2025.1/discrepancy-register.md` - Docs/reflection discrepancy inputs from Task 5.
  - Source: `resources/manifest/2025.1/added-since-2024.1.json` - 2025-only inventory from Task 3.

  **Acceptance Criteria**:
  - [ ] `resources/coverage/2025.1/added-api-classification.json` exists and includes every added/changed 2025 API exactly once.
  - [ ] `python -m pytest tests/unit/test_2025_1_added_api_classification.py -q` exits 0.
  - [ ] No 2025-only API is behavior-promoted without live/destructive evidence.

  **QA Scenarios**:
  ```
  Scenario: Every 2025-only API classified
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2025_1_added_api_classification.py -q`.
    Expected: Exit 0; every entry in `added-since-2024.1.json` appears exactly once with reason and source evidence.
    Evidence: .sisyphus/evidence/task-2025-6-added-classification.txt

  Scenario: Unclear semantics defer
    Tool: Bash
    Steps: Run tests with a fixture entry whose docs/reflection semantics conflict.
    Expected: Entry is `deferred` with `docs_reflection_mismatch`; no promotion occurs.
    Evidence: .sisyphus/evidence/task-2025-6-defer-on-mismatch.txt
  ```

  **Commit**: YES | Message: `test(coverage): classify 2025 api deltas` | Files: `resources/coverage/2025.1/added-api-classification.json`, `tests/unit/test_2025_1_added_api_classification.py`, `.sisyphus/evidence/task-2025-6-*.txt`

- [ ] 7. Generate 2025.1 coverage, deferred, and policy baseline

  **What to do**: Generate `resources/coverage/2025.1/api-coverage.json`, `live-coverage-matrix.json`, `phase2-coverage-summary.json`, `phase21-uri-policy.json`, and `resources/deferred/2025.1.json` from 2025 manifest, 2025 source notes, and Task 6 classification. Derive 2024 baseline counts from existing 2024 resources during execution and record comparison, but do not force 2025 counts to match 2024. Initially treat 2024 candidate promoted families as candidates only; all non-evidenced 2025 entries remain deferred/excluded.
  **Must NOT do**: Do not mark support as `live-tested` or `sandbox-mutating-tested` before Tasks 9 and 11 evidence exists.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Generated resources and accounting tests.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: Tasks 8, 12, 14 | Blocked By: Tasks 3, 5, 6

  **References**:
  - Pattern: `wwise_waapi/deferred_registry.py:1-27,89-170,174-240` - Deferred evidence schema and validation.
  - Pattern: `tests/unit/test_2024_api_resource_coverage.py:47-180` - 2024 coverage assertions.
  - Pattern: `tests/unit/test_2024_deferred_registry.py:30-111` - 2024 deferred registry behavior.
  - Pattern: `wwise_waapi/api_coverage.py:337-350` - Deterministic coverage resource writing.

  **Acceptance Criteria**:
  - [ ] Generated 2025 resources exist under `resources/coverage/2025.1/` and `resources/deferred/2025.1.json`.
  - [ ] `python -m pytest tests/unit/test_2025_1_api_resource_coverage.py tests/unit/test_2025_1_deferred_registry.py tests/unit/test_2025_1_live_coverage_matrix.py -q` exits 0.
  - [ ] Every reflected 2025 function is accounted for exactly once.
  - [ ] 2024 baseline comparison is recorded without treating 2024 proof as 2025 proof.

  **QA Scenarios**:
  ```
  Scenario: 2025 baseline reconciles
    Tool: Bash
    Steps: Run focused 2025 coverage/deferred/matrix tests.
    Expected: Exit 0; reflected function count equals coverage count equals matrix count.
    Evidence: .sisyphus/evidence/task-2025-7-resource-coverage.txt

  Scenario: No accidental promotions
    Tool: Bash
    Steps: Run tests that scan 2025 coverage for `live-tested` or `sandbox-mutating-tested` before evidence roots exist.
    Expected: No behavior-tested status appears without fresh 2025 evidence.
    Evidence: .sisyphus/evidence/task-2025-7-no-accidental-promotion.txt
  ```

  **Commit**: YES | Message: `test(coverage): classify 2025 parity resources` | Files: `resources/coverage/2025.1/*.json`, `resources/deferred/2025.1.json`, `tests/unit/test_2025_1_*coverage*.py`, `.sisyphus/evidence/task-2025-7-*.txt`

- [ ] 8. Add 2025 parity audits and fresh-evidence promotion guards

  **What to do**: Harden `tests/unit/test_2025_1_cross_version_audit.py` and add focused audits asserting 2025 coverage, live matrix, policy, deferred registry, source notes, WAQL resources, and docs references reconcile. Add promotion guards requiring evidence paths under `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/` or `resources/waql/2025.1/`, and rejecting stale 2022/2023/2024, bare 2025, skipped-test, manifest-only, helper-only, or NotebookLM-only proof as behavior evidence.
  **Must NOT do**: Do not allow approved evidence root alone; evidence must also be fresh 2025 proof and not stale proof embedded in text.

  **Recommended Agent Profile**:
  - Category: `deep` - Full resource reconciliation and guard design.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 2 | Blocks: Tasks 9, 11, 12, 14 | Blocked By: Tasks 4, 6, 7

  **References**:
  - Pattern: `tests/unit/test_2024_cross_version_audit.py:72-397` - Full reconciliation and stale-proof guards.
  - Pattern: `tests/unit/test_2024_live_coverage_matrix.py:36-175` - Matrix promotion constraints.
  - Pattern: `references/phase2-user-review-packet.md:5-10,47-80,98-130` - Review packet caveats.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2025_1_cross_version_audit.py tests/unit/test_2025_1_api_resource_coverage.py tests/unit/test_2025_1_deferred_registry.py tests/unit/test_2025_1_live_coverage_matrix.py -q` exits 0.
  - [ ] Tests reject 2024 evidence paths as 2025 behavior proof.
  - [ ] Tests reject manifest-only, skipped-test, helper-only, and NotebookLM-only behavioral promotion.

  **QA Scenarios**:
  ```
  Scenario: Full resource reconciliation passes
    Tool: Bash
    Steps: Run the focused 2025 audit command.
    Expected: Exit 0; all 2025 resource counts and policy assignments reconcile.
    Evidence: .sisyphus/evidence/task-2025-8-parity-audit.txt

  Scenario: Stale proof rejected
    Tool: Bash
    Steps: Run tests that inject 2024 evidence paths or bare 2025 paths into promoted entries.
    Expected: Tests pass by proving those entries are rejected as invalid proof.
    Evidence: .sisyphus/evidence/task-2025-8-stale-proof-rejected.txt
  ```

  **Commit**: YES | Message: `test(wwise): enforce 2025 parity audits` | Files: `tests/unit/test_2025_1_*.py`, resources only if audit-driven fixes are required, `.sisyphus/evidence/task-2025-8-*.txt`

- [ ] 9. Add 2025.1 live read-only WAQL and safe 2025-only evidence

  **What to do**: Port 2024 live read-only tests to `tests/live/test_2025_1_live_prerequisites.py`, `tests/live/test_2025_1_reflection_inventory.py`, and `tests/live/test_2025_1_waql_live_matrix.py`. Use `ak.wwise.core.object.get` as the required read-only candidate and add safe 2025-only read-only candidates from Task 6 only when docs, reflection, and SampleProject state permit. Write `resources/waql/2025.1/object-get-live-matrix.json` and per-case JSON evidence under `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/live-read-only/`. Promote only passed fresh 2025 read-only evidence.
  **Must NOT do**: Do not mutate project state. Do not promote 2025-only candidates whose docs/reflection/live behavior disagree.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Live WAQL tests and evidence accounting.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: Tasks 12, 14 | Blocked By: Tasks 1, 2, 3, 6, 8

  **References**:
  - Pattern: `tests/live/test_2024_live_prerequisites.py:21-102` - Exact prerequisite gate and skip evidence.
  - Pattern: `tests/live/test_2024_waql_live_matrix.py:38-242` - Read-only sandbox WAQL execution and evidence writer.
  - Pattern: `tests/unit/test_waql_live_matrix.py:53-132` - Generic WAQL matrix no-mutation contract.

  **Acceptance Criteria**:
  - [ ] Exact 2025 live command exits 0 or records prerequisite blocker before mutation.
  - [ ] `resources/waql/2025.1/object-get-live-matrix.json` exists if live prereqs pass.
  - [ ] `ak.wwise.core.object.get` is promoted only when fresh 2025 evidence passes.
  - [ ] Safe 2025-only read-only candidates are either promoted with evidence or deferred with reason.

  **QA Scenarios**:
  ```
  Scenario: Exact 2025 live read-only suite passes
    Tool: Bash
    Steps: Run `WWISE_VERSION=2025.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" WWISE_LIVE=1 python -m pytest tests/live/test_2025_1_live_prerequisites.py tests/live/test_2025_1_reflection_inventory.py tests/live/test_2025_1_waql_live_matrix.py -q`.
    Expected: Exit 0; evidence written under 2025 paths; no mutation.
    Evidence: .sisyphus/evidence/task-2025-9-live-read-only.txt

  Scenario: Missing live prereq fails safely
    Tool: Bash
    Steps: Run prerequisite tests with wrong console/sample path in a controlled test case.
    Expected: Failure/skip occurs before sandbox copy or Wwise launch; blocker recorded.
    Evidence: .sisyphus/evidence/task-2025-9-live-prereq-blocker.txt
  ```

  **Commit**: YES | Message: `test(live): add 2025 read-only parity evidence` | Files: `tests/live/test_2025_1_*.py`, `resources/waql/2025.1/*.json`, `resources/coverage/2025.1/*.json`, `resources/deferred/2025.1.json`, `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/live-read-only/*`, `.sisyphus/evidence/task-2025-9-*.txt`

- [ ] 10. Add 2025.1 destructive sandbox safety gates

  **What to do**: Add `wwise_waapi/destructive_2025_sandbox.py` if a version-specific runtime is needed, or extend reusable sandbox helpers with 2025.1 exact-path guards. Add `tests/unit/test_2025_1_destructive_safety.py` asserting missing opt-ins, wrong version, wrong paths, installed SampleProject target, `tests/_org/2025.1` target, missing sandbox root, and source immutability all fail before mutation/launch. Keep default dispatcher unchanged.
  **Must NOT do**: Do not run destructive Wwise calls in this task. Do not weaken 2024 destructive runtime.

  **Recommended Agent Profile**:
  - Category: `unspecified-high` - Safety-critical test/runtime work.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: Tasks 11, 13 | Blocked By: Tasks 1, 2

  **References**:
  - Pattern: `wwise_waapi/sandbox_fixture.py:33-37,106-198,201-245,266-359` - Sandbox lock/copy/cleanup and source immutability.
  - Pattern: `tests/unit/test_2024_destructive_safety.py:40-190` - 2024 destructive safety gates.
  - Pattern: `wwise_waapi/live_environment.py:112-203,206-266` - Fail-fast live/destructive path guards.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2025_1_destructive_safety.py -q` exits 0.
  - [ ] Missing `WWISE_LIVE`, missing `WWISE_DESTRUCTIVE`, wrong `WWISE_VERSION`, installed SampleProject target, and `tests/_org/2025.1` target fail before sandbox prep/launch.
  - [ ] 2024 destructive safety tests still pass.

  **QA Scenarios**:
  ```
  Scenario: Destructive gates fail closed
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2025_1_destructive_safety.py -q`.
    Expected: Exit 0; tests prove unsafe configurations stop before mutation.
    Evidence: .sisyphus/evidence/task-2025-10-destructive-gates.txt

  Scenario: 2024 safety regression stays clean
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2024_destructive_safety.py -q`.
    Expected: Exit 0; 2025 changes do not weaken 2024 safety.
    Evidence: .sisyphus/evidence/task-2025-10-2024-safety-regression.txt
  ```

  **Commit**: YES | Message: `test(destructive): harden 2025 sandbox gates` | Files: `wwise_waapi/destructive_2025_sandbox.py` if needed, `tests/unit/test_2025_1_destructive_safety.py`, `.sisyphus/evidence/task-2025-10-*.txt`

- [ ] 11. Add 2025.1 copied-sandbox destructive parity evidence

  **What to do**: Port 2024 destructive tests to `tests/destructive/test_2025_1_project_mutation_sandbox.py`, `tests/destructive/test_2025_1_soundbank_audio_sandbox.py`, and `tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py`. Attempt 2024 candidate mutating APIs (`object.create/set/delete`, `undo.beginGroup/endGroup/undo`, `audio.import`, `soundbank.setInclusions`, `switchContainer.addAssignment/removeAssignment`) and safe 2025-only mutating candidates from Task 6 only when reversible and docs/reflection support them. Use unique object names, copied sandbox projects, readback/cleanup, and source immutability checks. Keep helper readbacks unpromoted unless independently tested.
  **Must NOT do**: Do not mutate installed SampleProject or `tests/_org/2025.1`. Do not promote helper-only readbacks as behavior.

  **Recommended Agent Profile**:
  - Category: `deep` - Live destructive evidence with safety constraints.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: Tasks 12, 14 | Blocked By: Tasks 2, 6, 8, 10

  **References**:
  - Pattern: `tests/destructive/test_2024_project_mutation_sandbox.py:12-207` - Object/undo destructive evidence and cleanup.
  - Pattern: `tests/destructive/test_2024_soundbank_audio_sandbox.py:14-287` - Audio/soundbank destructive evidence.
  - Pattern: `tests/destructive/test_2024_switchcontainer_assignment_sandbox.py:12-221` - SwitchContainer destructive evidence.
  - Pattern: `tests/unit/test_2024_live_coverage_matrix.py:36-175` - Promotion status accounting and helper treatment.

  **Acceptance Criteria**:
  - [ ] Exact 2025 destructive command exits 0 or records fail-closed blocker before mutation.
  - [ ] Fresh destructive evidence JSONs exist only under `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/destructive/`.
  - [ ] 2025 coverage updates promote only passed fresh 2025 copied-sandbox cases.
  - [ ] Source immutability checks prove installed SampleProject and `tests/_org/2025.1` unchanged.

  **QA Scenarios**:
  ```
  Scenario: Exact 2025 destructive suite passes
    Tool: Bash
    Steps: Run `WWISE_VERSION=2025.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 python -m pytest tests/destructive/test_2025_1_project_mutation_sandbox.py tests/destructive/test_2025_1_soundbank_audio_sandbox.py tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py -q`.
    Expected: Exit 0; copied-sandbox mutations pass and cleanup/readback evidence is written.
    Evidence: .sisyphus/evidence/task-2025-11-destructive-sandbox.txt

  Scenario: Runtime artifacts do not leak
    Tool: Bash
    Steps: Run `git status --short -- .sisyphus/runtime` and `git ls-files .sisyphus/runtime` after destructive tests.
    Expected: No tracked/staged runtime artifacts, copied projects, generated banks, logs, caches, or audio files.
    Evidence: .sisyphus/evidence/task-2025-11-no-runtime-artifacts.txt
  ```

  **Commit**: YES | Message: `test(destructive): add 2025 sandbox parity evidence` | Files: `tests/destructive/test_2025_1_*.py`, `resources/coverage/2025.1/*.json`, `resources/deferred/2025.1.json`, `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/destructive/*`, `.sisyphus/evidence/task-2025-11-*.txt`

- [ ] 12. Document 2025 parity evidence and docs/evals no-overclaim rules

  **What to do**: Add/update 2025 docs, eval metadata, and `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/parity-review-packet.md` so user-facing text states exact reflected counts, promoted live/destructive evidence, deferred/excluded counts, 2025-only classification, NotebookLM/doc discrepancies, and Windows caveat truthfully. Add `tests/unit/test_2025_1_docs_contract.py` rejecting broad support claims and stale proof wording.
  **Must NOT do**: Do not claim complete 2025 behavioral coverage. Do not describe macOS evidence as Windows validation.

  **Recommended Agent Profile**:
  - Category: `writing` - Documentation and wording contracts.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 3 | Blocks: Task 14 | Blocked By: Tasks 5, 7, 8, 9, 11

  **References**:
  - Pattern: `tests/unit/test_2024_docs_contract.py:90-217` - 2024 no-overclaim tests and exact command templates.
  - Pattern: `references/phase2-user-review-packet.md:5-10,47-80,98-130` - Review packet caveats.
  - Pattern: `tests/unit/test_eval_metadata.py:36-124` - Eval metadata categories and review workflow linkage.
  - Pattern: `references/eval-review-workflow.md:3-20,68-83` - Eval review contract and static fallback guidance.

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/unit/test_2025_1_docs_contract.py tests/unit/test_eval_metadata.py -q` exits 0.
  - [ ] Review packet states 2025 reflected counts and promoted counts from resources, not assumed 2024 counts.
  - [ ] Docs/evals reject full-support, all-API-live-tested, skipped-test-as-proof, and Windows-overclaim language.

  **QA Scenarios**:
  ```
  Scenario: Docs contract passes
    Tool: Bash
    Steps: Run `python -m pytest tests/unit/test_2025_1_docs_contract.py tests/unit/test_eval_metadata.py -q`.
    Expected: Exit 0; docs/evals have no broad 2025 behavioral overclaim.
    Evidence: .sisyphus/evidence/task-2025-12-docs-contract.txt

  Scenario: Review packet is evidence-scoped
    Tool: Bash
    Steps: Parse the 2025 parity review packet and compare counts to coverage/deferred resources.
    Expected: Counts match generated resources; Windows is a caveat, not a hard gate or validation claim.
    Evidence: .sisyphus/evidence/task-2025-12-review-packet.txt
  ```

  **Commit**: YES | Message: `docs(wwise): document 2025 parity evidence` | Files: `references/*.md` if needed, `evals/evals.json` if needed, `tests/unit/test_2025_1_docs_contract.py`, `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/parity-review-packet.md`, `.sisyphus/evidence/task-2025-12-*.txt`

- [ ] 13. Verify 2025 opt-in gates and 2022/2024 regression safety

  **What to do**: Prove default pytest remains Wwise-free/2022.1-compatible and 2025 live/destructive suites require explicit opt-in. Add or update gate tests as needed. Run default full suite, focused 2025 unit suite, 2024 regression tests after shared-code changes, live-without-opt-in skip/fail-safe check, and destructive-without-opt-in skip/fail-safe check. Record exact outputs.
  **Must NOT do**: Do not mark skipped live/destructive tests as behavior evidence.

  **Recommended Agent Profile**:
  - Category: `quick` - Verification/evidence after implementation tasks.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 4 | Blocks: Task 14 | Blocked By: Tasks 1, 4, 10

  **References**:
  - Pattern: `tests/conftest.py:15-32` - Live/destructive skip gates.
  - Pattern: `references/long-run-runbook.md:181-199` - Default Wwise-free workflow.
  - Pattern: `tests/unit/test_live_runbook_constraints.py:15-192` - Runbook/env/approval constraints.
  - Pattern: `tests/unit/test_no_silent_skips.py:20-67` - No silent skips for reflected APIs.

  **Acceptance Criteria**:
  - [ ] `python -m pytest -q` exits 0 without launching Wwise.
  - [ ] `python -m pytest tests/unit/test_2025_1_*.py -q` exits 0.
  - [ ] 2025 live/destructive tests without opt-in skip or fail before mutation with documented reason.
  - [ ] 2024 regression command exits 0.

  **QA Scenarios**:
  ```
  Scenario: Default suite remains Wwise-free
    Tool: Bash
    Steps: Run `python -m pytest -q` with no `WWISE_LIVE`/`WWISE_DESTRUCTIVE`.
    Expected: Exit 0; live/destructive suites skipped as opt-in and no WwiseConsole launch required.
    Evidence: .sisyphus/evidence/task-2025-13-default-suite.txt

  Scenario: Opt-in gates block unsafe execution
    Tool: Bash
    Steps: Run 2025 live/destructive test selection without required env vars.
    Expected: Skip/fail-safe occurs before Wwise launch or sandbox mutation; output records reason.
    Evidence: .sisyphus/evidence/task-2025-13-opt-in-gates.txt
  ```

  **Commit**: YES | Message: `test(wwise): verify 2025 opt-in gates` | Files: `tests/unit/test_2025_1_*.py` if updated, `.sisyphus/evidence/task-2025-13-*.txt`

- [ ] 14. Final 2025 resource, evidence, and artifact reconciliation

  **What to do**: Reconcile all 2025 resources and evidence after Tasks 1-13. Confirm no orphan APIs, no stale 2022/2023/2024 proof in explicit 2025 resources, no missing evidence files for promoted entries, no risky accidental promotions, no docs contradictions, no runtime artifacts staged/tracked, and no 2025-only API left unclassified. Update 2025 parity review packet with final command results and counts.
  **Must NOT do**: Do not silently drop APIs to make counts pass; do not run unplanned 2026/generalized work.

  **Recommended Agent Profile**:
  - Category: `deep` - End-to-end reconciliation.
  - Skills: [] - No specialized skill required.
  - Omitted: [`frontend-ui-ux`] - No UI.

  **Parallelization**: Can Parallel: NO | Wave 4 | Blocks: F1-F4 | Blocked By: Tasks 9, 11, 12, 13

  **References**:
  - Pattern: `tests/unit/test_2024_cross_version_audit.py:72-397` - Full resource reconciliation.
  - Pattern: `.sisyphus/evidence/task-2024-13-final-reconciliation.txt` - 2024 final reconciliation evidence model.
  - Pattern: `.sisyphus/notepads/wwise-2024-waapi-integration-coverage/issues.md:21` - `.txt` evidence validation gotcha.

  **Acceptance Criteria**:
  - [ ] Focused 2025 unit audit command exits 0.
  - [ ] Exact 2025 live command exits 0 or records prerequisite blocker with no mutation.
  - [ ] Exact 2025 destructive command exits 0 or records fail-closed blocker with no mutation.
  - [ ] `python -m pytest -q` exits 0.
  - [ ] `git status --short -- .sisyphus/runtime` and `git ls-files .sisyphus/runtime` produce no tracked/staged runtime artifacts.

  **QA Scenarios**:
  ```
  Scenario: Full 2025 parity verification passes
    Tool: Bash
    Steps: Run focused 2025 unit audit, exact 2025 live command, exact 2025 destructive command, 2024 regression command, and default full pytest.
    Expected: All commands exit 0 or document safe prerequisite blockers; review packet updated with final counts/results.
    Evidence: .sisyphus/evidence/task-2025-14-final-reconciliation.txt

  Scenario: No runtime/generated artifact leakage
    Tool: Bash
    Steps: Run `git status --short`, `git status --short -- .sisyphus/runtime`, and `git ls-files .sisyphus/runtime`.
    Expected: No runtime sandbox, generated banks, logs, caches, generated audio, copied SampleProject artifacts, or unrelated evidence staged/tracked.
    Evidence: .sisyphus/evidence/task-2025-14-no-runtime-artifacts.txt
  ```

  **Commit**: YES | Message: `test(wwise): reconcile 2025 parity evidence` | Files: `resources/coverage/2025.1/*.json`, `resources/deferred/2025.1.json`, `resources/waql/2025.1/*.json`, `tests/unit/test_2025_1_*.py`, `tests/live/test_2025_1_*.py`, `tests/destructive/test_2025_1_*.py`, `references/*.md`, `evals/evals.json`, `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/*`, `.sisyphus/evidence/task-2025-14-*.txt`

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
- Never stage `.sisyphus/runtime`, copied sandbox projects, Wwise logs, generated banks, generated audio, `__pycache__`, `.coverage`, NotebookLM auth state, or unrelated evidence from other plans.

## Success Criteria
- 2025.1 reflected API count is discovered and every reflected API is accounted for exactly once.
- 2025.1 resources are version-isolated and fail closed with no 2022/2023/2024/global/bare-2025 fallback.
- 2025.1 behavioral/live/destructive counts are backed only by fresh 2025.1 evidence.
- 2025-only APIs are classified, safely attempted where possible, or deferred/excluded with evidence-backed reasons.
- Risky families remain deferred/excluded unless explicitly and safely evidenced.
- Default pytest remains Wwise-free and 2022.1-default.
- 2024 regression tests pass after shared-code changes.
- Review packet states Windows is non-blocking evidence/caveat, not a hard gate.
