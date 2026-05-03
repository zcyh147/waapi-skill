# Wwise WAAPI long-run execution runbook

Use this runbook for long Wwise WAAPI implementation sessions that follow `.sisyphus/plans/wwise-waapi-skills.md`. The primary execution path is `/start-work`; the Ralph-loop path is optional and guarded for unusually long runs only.

## Primary path: `/start-work`

Run `/start-work` against `.sisyphus/plans/wwise-waapi-skills.md` for normal execution. This path keeps the plan as the source of truth, preserves task boundaries, and lets each task produce its own tests and evidence before final verification.

Required behavior for `/start-work`:

- Follow the plan exactly and preserve existing plan constraints.
- Start with the headless first gate: WwiseConsole lifecycle, dynamic WAAPI port, readiness probe, bounded startup, bounded shutdown, stdout and stderr capture, and process-tree cleanup.
- Use TDD for each task: write or update failing tests first, implement the smallest compliant change, then run targeted and default pytest verification.
- Keep overall line and branch coverage >=85%, and keep core headless, manifest, generator, and timeout module coverage >=95%.
- Treat NotebookLM notebook `wwise-2022.1-docs` as the mandatory NotebookLM gate before 2022.1 WAQL or API semantic source-note refresh. For 2021.1, use `wwise-2021.1.14-docs` only to generate or refresh persisted local source-only evidence under `references/semantic/2021.1/` and `resources/semantic/2021.1/source_notes.json`. For 2023.1, use `wwise-2023.1-docs` only to generate or refresh persisted local evidence under `references/semantic/2023.1/` and `resources/semantic/2023.1/source_notes.json`. For 2024.1, use `wwise-2024.1-docs` only to generate or refresh persisted local evidence under `references/semantic/2024.1/` and `resources/semantic/2024.1/source_notes.json`. For 2025.1, use `wwise-2025.1-docs` only to generate or refresh persisted local evidence under `references/semantic/2025.1/` and `resources/semantic/2025.1/source_notes.json`.
- Never allow silent skips. Every reflected Wwise 2022.1 function and topic must be implemented and tested, or recorded in the deferred registry with required evidence.
- Enforce deferred registry completeness before claiming Wwise 2022.1 API coverage.
- Use bounded waits only. No unbounded waits are allowed for readiness, WAAPI calls, subscriptions, listener joins, process startup, or process cleanup.
- Never mutate user Wwise projects. Live and destructive work must use isolated fixture projects and explicit opt-in gates.
- Keep 2021.1, 2023.1, 2024.1, and 2025.1 support explicit and evidence-scoped. Each version is supported only where resources, source notes, tests, and evidence exist.
- Keep Windows validation truthful: macOS-only evidence is a non-blocking caveat and cannot claim cross-platform completion.

## Optional path: guarded Ralph-loop

Use Ralph-loop only when a single agent must run the accepted plan for a long period and the operator understands the stop conditions. Do not start a Ralph loop from this runbook automatically.

Copy this prompt exactly when the optional path is chosen:

```text
Run a guarded Ralph loop for `.sisyphus/plans/wwise-waapi-skills.md` until all non-final tasks are implemented and verified. Treat `/start-work` as the primary execution path; use this Ralph loop only as the optional long-run path.

Obey the plan exactly. Do not weaken plan constraints for speed. Do not modify the plan file. Do not commit unless a separate orchestrator explicitly delegates git work.

Critical constraints:
1. No silent skips: every reflected Wwise 2022.1 function and topic must be implemented and tested, or deferred with complete evidence in the deferred registry.
2. Headless first: complete the WwiseConsole lifecycle gate before broad API generation. Use dynamic WAAPI ports, readiness probes, stdout and stderr capture, bounded startup and shutdown timeouts, and forced process-tree cleanup.
3. NotebookLM gate: use notebook id `wwise-2022.1-docs` as the mandatory NotebookLM gate before 2022.1 WAQL or API semantic source-note refresh. Use `wwise-2021.1.14-docs` only for 2021.1 persisted source-only source-note evidence refresh, `wwise-2023.1-docs` only for 2023.1 persisted source-note evidence refresh, `wwise-2024.1-docs` only for 2024.1 persisted source-note evidence refresh, and `wwise-2025.1-docs` only for 2025.1 persisted source-note evidence refresh. Runtime builders must read local persisted evidence and must not query NotebookLM.
4. TDD: add or update tests before implementation, then run the targeted tests for the changed behavior.
5. Coverage thresholds: maintain overall line and branch coverage >=85%, plus >=95% coverage for core headless, manifest, generator, and timeout modules.
6. No unbounded waits: every WAAPI call, subscription wait, listener join, process startup, process run, and shutdown path needs a bounded timeout.
7. No user-project mutation: unit tests use fakes, live tests use isolated fixture projects, and destructive tests require explicit opt-in.
8. Deferred registry enforcement: do not claim Wwise 2022.1 API coverage until deferred entries have required evidence fields and the coverage audit passes.
9. Windows gate truthfulness: do not claim Windows-host validation from macOS-only evidence. Record Windows validation as pending or as a non-blocking caveat unless live Windows-host evidence exists.
10. Final verification with user approval: after all implementation tasks and final verification commands finish, present consolidated verification results and wait for explicit user okay before marking completion.

Stop conditions:
- Stop immediately on any safety risk, secret or auth state exposure, user-project mutation risk, orphan process risk, or unbounded wait risk.
- Stop docs-dependent generation if the NotebookLM gate for the requested version is missing, wrong, or fail-closed. For source-note refresh, the requested version must match the persisted local evidence path and notebook id.
- Stop live or destructive validation if no isolated fixture project and explicit opt-in are available.
- Stop cross-platform claims when Windows evidence is absent, pending, or captured only on macOS.
- Stop final completion after presenting verification results. Wait for explicit user okay before marking final verification complete.

Required evidence paths:
- `.sisyphus/evidence/task-1-headless-lifecycle.md`
- `.sisyphus/evidence/task-2-scaffold.md`
- `.sisyphus/evidence/task-3-reflection-manifest.md`
- `.sisyphus/evidence/task-7-api-coverage.md`
- `.sisyphus/evidence/task-8-waql-docs.md`
- `.sisyphus/evidence/task-10-notebooklm-gate.md`
- `.sisyphus/evidence/task-11-windows-gate.md`
- `.sisyphus/evidence/task-12-runbook.md`
- `.sisyphus/evidence/task-12-approval-stop.md`
```


## Semantic builder and source-note refresh workflow

Default development remains Wwise-free. Semantic builders use persisted source notes in `resources/semantic/2022.1/source_notes.json` by default. 2021.1, 2023.1, 2024.1, and 2025.1 callers must explicitly use versioned resources such as `resources/semantic/2021.1/source_notes.json`, `resources/semantic/2023.1/source_notes.json`, `resources/semantic/2024.1/source_notes.json`, `resources/semantic/2025.1/source_notes.json`, and references under the matching `references/semantic/<version>/` directory. Builders return previews, dispatcher-ready payloads, readback plans, or topic expectations only. They do not execute live WAAPI calls by default.

Refresh the source-note gate only when semantic docs change:

1. Query NotebookLM notebook `wwise-2022.1-docs` for 2022.1 families and save the accepted gate evidence in `references/semantic-builder-notebooklm-gate.md`. Query `wwise-2021.1.14-docs` only for 2021.1 source-note refresh and save accepted source-only evidence under `references/semantic/2021.1/`. Query `wwise-2023.1-docs` only for 2023.1 source-note refresh and save accepted evidence under `references/semantic/2023.1/`. Query `wwise-2024.1-docs` only for 2024.1 source-note refresh and save accepted evidence under `references/semantic/2024.1/`. Query `wwise-2025.1-docs` only for 2025.1 source-note refresh and save accepted evidence under `references/semantic/2025.1/`.
2. Update the family note in the matching local source-note resource, `resources/semantic/2022.1/source_notes.json`, `resources/semantic/2023.1/source_notes.json`, `resources/semantic/2024.1/source_notes.json`, or `resources/semantic/2025.1/source_notes.json`, with cited required fields and the exact endpoint inventory.
3. Run `python -m pytest tests/unit/test_semantic_builder_source_notes.py tests/unit/test_semantic_builder_audit.py -q`.
4. Do not promote profiler, transport, soundengine, UI, CLI, remote, or debug APIs into semantic builders without a new plan and source-note approval.

Use these command tiers for semantic builder work:

```bash
python -m pytest tests/unit/test_semantic_builder_audit.py -q
python -m pytest tests/unit/test_semantic_builder_query.py tests/unit/test_semantic_builder_object_mutation.py tests/unit/test_semantic_builder_properties.py tests/unit/test_semantic_builder_import.py tests/unit/test_semantic_builder_soundbank.py tests/unit/test_semantic_builder_switchcontainer.py -q
WWISE_LIVE=1 python -m pytest tests/live/test_waql_live_matrix.py -q
WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2022.1 python -m pytest tests/destructive/test_project_mutation_sandbox.py tests/destructive/test_soundbank_audio_sandbox.py tests/destructive/test_switchcontainer_assignment_sandbox.py -q
```

Live and destructive tests skip unless the matching environment variables are explicitly set. Never treat a skipped live/destructive suite as proof of live execution.

Timeout tuning is a diagnostic fallback, not the primary fix. If startup or readiness times out after gates and prerequisites pass, inspect getInfo readiness diagnostics, argv, cwd, dynamic port, process state, and output tails before raising `WWISE_READINESS_TIMEOUT`. A timeout increase may preserve evidence for a slow host, but it does not turn a blocked or failed runtime launch into a pass.

NotebookLM boundary: NotebookLM produces or refreshes source evidence only. Runtime code reads local persisted source notes and evidence files. Do not add a runtime NotebookLM dependency or imply that builders query NotebookLM while constructing previews.

## Wwise 2021.1 versioned support scope

Wwise 2021.1 support is explicit and scoped to committed resources, source notes, tests, and evidence. It has reflected inventory and parity classification for 99 functions. Do not claim broad 2021.1 WAAPI behavioral coverage. Manifest reflection proves inventory only, source notes and NotebookLM notes are source-only, and skipped live or destructive tests are not live evidence.

Versioned 2021.1 layout:

- `references/semantic/2021.1/`
- `resources/manifest/2021.1/`
- `resources/semantic/2021.1/source_notes.json`
- `tests/destructive/support/resources/capabilities/2021.1/`
- `resources/waql/2021.1/`
- `resources/deferred/2021.1.json`
- `tests/_org/2021.1/`

Accepted 2021.1 behavior evidence is limited to one live read-only URI, `ak.wwise.core.object.get`, and these nine copied-sandbox mutating URIs:

- `ak.wwise.core.audio.import`
- `ak.wwise.core.object.create`
- `ak.wwise.core.object.delete`
- `ak.wwise.core.object.setNotes`
- `ak.wwise.core.soundbank.setInclusions`
- `ak.wwise.core.switchContainer.addAssignment`
- `ak.wwise.core.switchContainer.removeAssignment`
- `ak.wwise.core.undo.beginGroup`
- `ak.wwise.core.undo.endGroup`

The status split is supported 0, behavioral 0, deferred 43, excluded 46, live-tested 1, sandbox-mutating-tested 9, and unknown 0. `ak.wwise.core.soundbank.getInclusions` and `ak.wwise.core.switchContainer.getAssignments` are readback helpers only. `ak.wwise.core.object.setReference` was setup helper evidence only for the switchContainer test. The installed SampleProject is immutable source only, and destructive tests must only mutate copied sandboxes under `WWISE_SANDBOX_ROOT`.

Exact 2021.1 command templates:

```bash
python -m pytest -q

WWISE_VERSION=2021.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" \
WWISE_LIVE=1 \
python -m pytest tests/live/test_2021_1_live_prerequisites.py tests/live/test_2021_1_reflection_prerequisites.py tests/live/test_2021_1_object_get_matrix.py -q

WWISE_VERSION=2021.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2021.1 \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive/test_2021_1_project_mutation_sandbox.py tests/destructive/test_2021_1_soundbank_audio_sandbox.py tests/destructive/test_2021_1_switchcontainer_assignment_sandbox.py -q
```

## Wwise 2023.1 versioned support scope

Wwise 2023.1 support is explicit and scoped to committed resources, source notes, tests, and evidence. Do not claim full 2023.1 WAAPI behavioral coverage. Manifest reflection proves inventory only, and skipped live or destructive tests are not live evidence.

Versioned 2023.1 layout:

- `references/semantic/2023.1/`
- `resources/manifest/2023.1/`
- `resources/semantic/2023.1/source_notes.json`
- `tests/destructive/support/resources/capabilities/2023.1/`
- `resources/waql/2023.1/`
- `resources/deferred/2023.1.json`
- `tests/_org/2023.1/`

Exact 2023.1 command templates:

```bash
WWISE_VERSION=2023.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" \
WWISE_LIVE=1 \
python -m pytest tests/live -q

WWISE_VERSION=2023.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2023.1 \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive -q
```

The 2023.1 lane remains separate from the 2024.1 and 2025.1 lanes.

## Wwise 2024.1 versioned support scope

Wwise 2024.1 support is explicit and scoped to committed resources, source notes, tests, and evidence. It has complete reflected inventory and parity classification for 148 functions. Do not claim broad 2024.1 WAAPI behavioral coverage. Manifest reflection proves inventory only, and skipped live or destructive tests are not live evidence.

Versioned 2024.1 layout:

- `references/semantic/2024.1/`
- `resources/manifest/2024.1/`
- `resources/semantic/2024.1/source_notes.json`
- `tests/destructive/support/resources/capabilities/2024.1/`
- `resources/waql/2024.1/`
- `resources/deferred/2024.1.json`
- `tests/_org/2024.1/`

Accepted 2024.1 behavior evidence is limited to one live read-only URI, `ak.wwise.core.object.get`, and these ten copied-sandbox mutating URIs:

- `ak.wwise.core.audio.import`
- `ak.wwise.core.object.create`
- `ak.wwise.core.object.delete`
- `ak.wwise.core.object.set`
- `ak.wwise.core.soundbank.setInclusions`
- `ak.wwise.core.switchContainer.addAssignment`
- `ak.wwise.core.switchContainer.removeAssignment`
- `ak.wwise.core.undo.beginGroup`
- `ak.wwise.core.undo.endGroup`
- `ak.wwise.core.undo.undo`

The remaining 137 entries are deferred or excluded. `ak.wwise.core.soundbank.getInclusions` and `ak.wwise.core.switchContainer.getAssignments` are readback helpers only and remain unpromoted. Risky families remain excluded or deferred unless a later plan adds fresh evidence and review.

Exact 2024.1 command templates:

```bash
python -m pytest -q

WWISE_VERSION=2024.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" \
WWISE_LIVE=1 \
python -m pytest tests/live/test_2024_live_prerequisites.py tests/live/test_2024_reflection_inventory.py tests/live/test_2024_waql_live_matrix.py -q

WWISE_VERSION=2024.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2024.1 \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive/test_2024_project_mutation_sandbox.py tests/destructive/test_2024_soundbank_audio_sandbox.py tests/destructive/test_2024_switchcontainer_assignment_sandbox.py -q
```

## Wwise 2025.1 versioned support scope

Wwise 2025.1 support is explicit and scoped to committed resources, source notes, tests, and evidence. It has complete reflected inventory and parity classification for 154 functions. Do not claim broad 2025.1 WAAPI behavioral coverage. Manifest reflection proves inventory only, 2024 evidence is comparison metadata only, and skipped live or destructive tests are not live evidence.

Versioned 2025.1 layout:

- `references/semantic/2025.1/`
- `resources/manifest/2025.1/`
- `resources/semantic/2025.1/source_notes.json`
- `tests/destructive/support/resources/capabilities/2025.1/`
- `resources/waql/2025.1/`
- `resources/deferred/2025.1.json`
- `tests/_org/2025.1/`

Accepted 2025.1 behavior evidence is limited to one live read-only URI, `ak.wwise.core.object.get`, and these ten copied-sandbox mutating URIs:

- `ak.wwise.core.audio.import`
- `ak.wwise.core.object.create`
- `ak.wwise.core.object.delete`
- `ak.wwise.core.object.set`
- `ak.wwise.core.soundbank.setInclusions`
- `ak.wwise.core.switchContainer.addAssignment`
- `ak.wwise.core.switchContainer.removeAssignment`
- `ak.wwise.core.undo.beginGroup`
- `ak.wwise.core.undo.endGroup`
- `ak.wwise.core.undo.undo`

The remaining 143 entries are deferred or excluded, split as 95 deferred and 48 excluded. `ak.wwise.core.soundbank.getInclusions` and `ak.wwise.core.switchContainer.getAssignments` are readback helpers only and remain unpromoted. NotebookLM-only text and URL candidates are source-note caveats, not runtime proof. Windows validation remains a follow-up caveat because macOS evidence is not Windows-host validation.

Exact 2025.1 command templates:

```bash
python -m pytest -q

WWISE_VERSION=2025.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" \
WWISE_READINESS_TIMEOUT=180 \
WWISE_LIVE=1 \
python -m pytest tests/live/test_2025_1_live_prerequisites.py tests/live/test_2025_1_reflection_inventory.py tests/live/test_2025_1_waql_live_matrix.py -q

WWISE_VERSION=2025.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2025.1 \
WWISE_READINESS_TIMEOUT=180 \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive/test_2025_1_project_mutation_sandbox.py tests/destructive/test_2025_1_soundbank_audio_sandbox.py tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py -q
```

## Final verification approval stop

Final verification is not self-completing. After targeted tests, full pytest, coverage, live-gated evidence review, Windows gate review, and final review agents complete, present the verification results to the user and wait for explicit user okay before marking the final verification wave complete.

The approval stop must be recorded in `.sisyphus/evidence/task-12-approval-stop.md`. The runbook constraint test evidence belongs in `.sisyphus/evidence/task-12-runbook.md`.

## Live sandbox execution modes

Use these commands from the repository root. Default pytest must stay Wwise-free, and live or destructive suites must be opt-in through environment variables.

Phase 2.1 uses five workflow families:

- Default workflow: `python -m pytest -q` must remain Wwise-free.
- Unit workflow: targeted unit tests validate generated coverage resources, deferred evidence rules, and review-packet wording without launching Wwise.
- Live workflow: `WWISE_LIVE=1` read-only suites may inspect copied fixture projects after prerequisites pass.
- Destructive workflow: `WWISE_LIVE=1 WWISE_DESTRUCTIVE=1` suites may mutate only copied sandboxes under `WWISE_SANDBOX_ROOT`.
- Profiler workflow: profiler, transport, and soundengine probes may record capability or blocker evidence, but accepted calls alone never promote coverage.

After active gates and prerequisites pass, WwiseConsole startup, getInfo readiness, live read-only runtime, and copied-sandbox destructive runtime failures fail the active suite. They are not collection skips and cannot fall back to fake routes. Missing prerequisites may stop the workflow before launch, but once runtime startup begins, blocked launch, early exit, readiness timeout, or teardown safety failure is failure evidence.

Task 4, Task 5, Task 6, Task 8, and Task 9 evidence in `.sisyphus/evidence/waapi-test-remediation/` records Wwise-launch-blocked or no-gate static validation because the operator instructed agents not to launch Wwise. Those blockers are honest evidence, not runtime pass evidence, and must not be counted as fresh active live or destructive behavior.

2021.1, 2024.1, and 2025.1 topic inventory is now present in versioned coverage resources. Task 8 topic plans are bounded, safe, and non-behavioral until fresh active live topic publisher and subscription evidence exists.

For 2022.1, inventory, substitute coverage, fake-route entries, and deferred entries stay separate from behavior. Fake-route-tested and deferred rows may explain route or inventory accounting, but they do not count as behavioral or live behavioral coverage.

### Default Wwise-free verification

```bash
python -m pytest -q
```

Expected result: unit tests pass without launching Wwise, opening WwiseConsole, requiring SampleProject, or reading live credentials.

### Unit coverage and packet verification

```bash
python -m pytest tests/unit/test_phase2_coverage_summary.py tests/unit/test_live_runbook_constraints.py -q
```

Expected result: generated Phase 2.1 status accounting and the user review packet agree on the final counts. Unit tests may read committed resources such as `tests/destructive/support/resources/capabilities/2022.1/phase2-coverage-summary.json`, but they must not require a live authoring process or mutate fixture source files.

### Live smoke prerequisites

```bash
WWISE_LIVE=1 \
WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject \
python -m pytest tests/live/test_live_prerequisites.py -q
```

Expected result: the prerequisite gate proves that the local Wwise 2022.1 console and immutable SampleProject source are present. If the gate fails, do not run live or destructive suites. Record the exact missing prerequisite instead.

The committed `tests/_org/2022.1` tree is immutable fixture source, not disposable runtime state. Sandbox tests copy from `tests/_org/2022.1` or from the installed SampleProject source named by `WWISE_SAMPLE_PROJECT_PATH`; normal tests must never mutate either source fixture tree.

### Live sandbox read-only workflows

```bash
WWISE_LIVE=1 \
WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject \
python -m pytest tests/live/test_waql_live_matrix.py tests/live/test_object_topics_sandbox.py -q
```

Expected result: read-only live checks use SampleProject as the source fixture and keep generated evidence bounded to the test output and `.sisyphus/evidence/wwise-waapi-live-sandbox-coverage/` when explicitly written by the suite.

### Destructive sandbox workflows

```bash
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2022.1 \
python -m pytest tests/destructive/test_project_mutation_sandbox.py tests/destructive/test_soundbank_audio_sandbox.py -q
```

Destructive tests must only mutate copied sandboxes under `WWISE_SANDBOX_ROOT`. Never point `WWISE_FIXTURE_PROJECT` at a source project, production project, user project, or any `.wproj` outside the active sandbox root.

### Keep-on-failure evidence workflow

```bash
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
WWISE_SANDBOX_KEEP_ON_FAILURE=1 \
WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2022.1 \
python -m pytest tests/destructive/test_project_mutation_sandbox.py -q
```

When a destructive sandbox fails and `WWISE_SANDBOX_KEEP_ON_FAILURE=1` is set, inspect the preserved sandbox and evidence under `.sisyphus/evidence/wwise-waapi-live-sandbox-coverage/`. Compare copied `.wproj`, `.wwu`, generated bank, audio, and log artifacts there. Do not commit preserved sandboxes, generated banks, generated audio, runtime logs, caches, `.venv`, or auth/session state.

Committed fixture `.wav` inputs under `tests/_org/2022.1` are handled through Git LFS and may be used as source audio for copied sandboxes. Generated `.wav` files, converted audio, SoundBank output, profiler captures, runtime sandboxes, caches, auth state, and session state are runtime artifacts and must not be committed.

### Prerequisite failure workflow

```bash
WWISE_LIVE=1 \
WWISE_SAMPLE_PROJECT_PATH=/missing/or/unavailable/SampleProject \
python -m pytest tests/live/test_live_prerequisites.py -q
```

Expected result: with `WWISE_LIVE=1` set, missing Wwise or SampleProject prerequisites must fail fast with a clear prerequisite error before any live or destructive workflow continues. Do not silently skip, fall back to fake routes, or treat the live opt-in failure as substitute coverage. Fix the local prerequisite, then rerun the live smoke command before trying category suites again.

### Windows-pending workflow

```bash
python -m pytest tests/unit/test_phase2_coverage_summary.py -q
```

Expected result: the summary keeps `windows_validation` as `pending` unless Windows-host evidence exists. macOS-generated `GeneratedSoundBanks/Windows` artifacts are sandbox output only, not Windows validation.

## Live environment variables

- `WWISE_SAMPLE_PROJECT_PATH`: immutable source-to-copy fixture path. The local example is `/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject`. This source is copied because tests need disposable sandboxes while the installed SampleProject stays unchanged and is not committed or vendored.
- `WWISE_FIXTURE_PROJECT`: active copied `.wproj` used by a live or destructive test. For destructive runs, it must be under `WWISE_SANDBOX_ROOT`.
- `WWISE_SANDBOX_ROOT`: root directory for copied sandbox projects. Use a versioned runtime path such as `.sisyphus/runtime/wwise-waapi-sandboxes/2022.1`, `.sisyphus/runtime/wwise-waapi-sandboxes/2023.1`, `.sisyphus/runtime/wwise-waapi-sandboxes/2024.1`, or `.sisyphus/runtime/wwise-waapi-sandboxes/2025.1`.
- `WWISE_SANDBOX_KEEP_ON_FAILURE`: set to `1` to preserve a failing sandbox and evidence for inspection. Leave unset for normal cleanup.
- `WWISE_LIVE`: set to `1` to opt into live Wwise prerequisite and read-only sandbox suites.
- `WWISE_DESTRUCTIVE`: set to `1` together with `WWISE_LIVE=1` to opt into copied-sandbox mutation suites. It has no destructive effect without the live gate.

## Phase 2.1 status meanings

- `fake-route-tested`: Phase 1 fake-route coverage remains accepted as inventory/substitute evidence for non-policy APIs, but it is not behavioral or live behavioral coverage.
- `sandbox-mutating-tested`: copied-sandbox behavior evidence exists and counts as live behavioral coverage.
- `skipped-approved`: user-approved inventory-only exclusion, not behavioral or live behavioral coverage.
- `wrapper-only`: wrapper diagnostics or route coverage only, not behavioral or live behavioral coverage.
- `conformance-only-skip`: user-approved reflected schema and route conformance only, not behavioral or live behavioral coverage.
- `still-deferred-with-evidence`: blocker evidence and future review trigger exist, but coverage is not promoted.

## Rerunning failed category suites

Rerun only the failed category after the prerequisite smoke test passes. Keep the same env contract so evidence remains comparable.

```bash
WWISE_LIVE=1 WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject python -m pytest tests/live/test_waql_live_matrix.py -q
WWISE_LIVE=1 WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject python -m pytest tests/live/test_profiler_transport_soundengine.py -q
WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2022.1 python -m pytest tests/destructive/test_soundbank_audio_sandbox.py -q
```

Accepted WAAPI calls alone are not coverage. Promotion requires bounded readback, topic payload, profiler payload, generated artifact, or cleanup evidence that matches the category contract.

For profiler, transport, and soundengine probes, accepted calls, returned IDs, empty mappings, capture start/stop, or no exceptions are context only. They do not promote coverage unless paired with the observable evidence required by the status contract.

## Runtime resource and topic-inventory caveats

Runtime builders and dispatcher flows do not query NotebookLM. Runtime reads local persisted evidence from packaged resources such as `resources/manifest/<version>/`, `resources/semantic/<version>/`, `tests/destructive/support/resources/capabilities/<version>/`, `resources/deferred/<version>.json`, and `resources/waql/<version>/`.

Manifest reflection proves inventory only. Manifest reflection, skipped live tests, and skipped destructive tests are not behavioral proof. topic inventory rows are inventory/substitute accounting only until fresh active live topic evidence exists.

Wwise 2023.1, 2024.1, and 2025.1 are supported only where versioned manifests, capability resources, deferred registries, semantic source notes, WAQL resources, tests, and evidence exist for that exact version.
