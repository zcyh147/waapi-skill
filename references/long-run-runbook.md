# Wwise WAAPI long-run execution runbook

Use this runbook for long Wwise WAAPI implementation sessions that follow `.sisyphus/plans/wwise-waapi-skills.md`. The primary execution path is `/start-work`; the Ralph-loop path is optional and guarded for unusually long runs only.

## Primary path: `/start-work`

Run `/start-work` against `.sisyphus/plans/wwise-waapi-skills.md` for normal execution. This path keeps the plan as the source of truth, preserves task boundaries, and lets each task produce its own tests and evidence before final verification.

Required behavior for `/start-work`:

- Follow the plan exactly and preserve existing plan constraints.
- Start with the headless first gate: WwiseConsole lifecycle, dynamic WAAPI port, readiness probe, bounded startup, bounded shutdown, stdout and stderr capture, and process-tree cleanup.
- Use TDD for each task: write or update failing tests first, implement the smallest compliant change, then run targeted and default pytest verification.
- Keep overall line and branch coverage >=85%, and keep core headless, manifest, generator, and timeout module coverage >=95%.
- Treat NotebookLM notebook `wwise-2022.1-docs` as the mandatory NotebookLM gate before WAQL or API semantic generation.
- Never allow silent skips. Every reflected Wwise 2022.1 function and topic must be implemented and tested, or recorded in the deferred registry with required evidence.
- Enforce deferred registry completeness before claiming Wwise 2022.1 API coverage.
- Use bounded waits only. No unbounded waits are allowed for readiness, WAAPI calls, subscriptions, listener joins, process startup, or process cleanup.
- Never mutate user Wwise projects. Live and destructive work must use isolated fixture projects and explicit opt-in gates.
- Keep 2023, 2024, and 2025 support as inert placeholders unless live reflected evidence exists.
- Keep Windows validation truthful: macOS-only evidence leaves the Windows gate pending and cannot claim cross-platform completion.

## Optional path: guarded Ralph-loop

Use Ralph-loop only when a single agent must run the accepted plan for a long period and the operator understands the stop conditions. Do not start a Ralph loop from this runbook automatically.

Copy this prompt exactly when the optional path is chosen:

```text
Run a guarded Ralph loop for `.sisyphus/plans/wwise-waapi-skills.md` until all non-final tasks are implemented and verified. Treat `/start-work` as the primary execution path; use this Ralph loop only as the optional long-run path.

Obey the plan exactly. Do not weaken plan constraints for speed. Do not modify the plan file. Do not commit unless a separate orchestrator explicitly delegates git work.

Critical constraints:
1. No silent skips: every reflected Wwise 2022.1 function and topic must be implemented and tested, or deferred with complete evidence in the deferred registry.
2. Headless first: complete the WwiseConsole lifecycle gate before broad API generation. Use dynamic WAAPI ports, readiness probes, stdout and stderr capture, bounded startup and shutdown timeouts, and forced process-tree cleanup.
3. NotebookLM gate: use notebook id `wwise-2022.1-docs` as the mandatory NotebookLM gate before WAQL or API semantic generation. If gate evidence is missing or fail-closed, stop docs-dependent work.
4. TDD: add or update tests before implementation, then run the targeted tests for the changed behavior.
5. Coverage thresholds: maintain overall line and branch coverage >=85%, plus >=95% coverage for core headless, manifest, generator, and timeout modules.
6. No unbounded waits: every WAAPI call, subscription wait, listener join, process startup, process run, and shutdown path needs a bounded timeout.
7. No user-project mutation: unit tests use fakes, live tests use isolated fixture projects, and destructive tests require explicit opt-in.
8. Deferred registry enforcement: do not claim Wwise 2022.1 API coverage until deferred entries have required evidence fields and the coverage audit passes.
9. Windows gate truthfulness: do not claim Windows validation passed from macOS-only evidence. Record Windows validation as pending unless live Windows-host evidence exists.
10. Final verification with user approval: after all implementation tasks and final verification commands finish, present consolidated verification results and wait for explicit user okay before marking completion.

Stop conditions:
- Stop immediately on any safety risk, secret or auth state exposure, user-project mutation risk, orphan process risk, or unbounded wait risk.
- Stop docs-dependent generation if the NotebookLM gate for `wwise-2022.1-docs` is missing, wrong, or fail-closed.
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

## Final verification approval stop

Final verification is not self-completing. After targeted tests, full pytest, coverage, live-gated evidence review, Windows gate review, and final review agents complete, present the verification results to the user and wait for explicit user okay before marking the final verification wave complete.

The approval stop must be recorded in `.sisyphus/evidence/task-12-approval-stop.md`. The runbook constraint test evidence belongs in `.sisyphus/evidence/task-12-runbook.md`.

## Live sandbox execution modes

Use these commands from the repository root. Default pytest must stay Wwise-free, and live or destructive suites must be opt-in through environment variables.

### Default Wwise-free verification

```bash
python -m pytest -q
```

Expected result: unit tests pass without launching Wwise, opening WwiseConsole, requiring SampleProject, or reading live credentials.

### Live smoke prerequisites

```bash
WWISE_LIVE=1 \
WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject \
python -m pytest tests/live/test_live_prerequisites.py -q
```

Expected result: the prerequisite gate proves that the local Wwise 2022.1 console and immutable SampleProject source are present. If the gate fails, do not run live or destructive suites. Record the exact missing prerequisite instead.

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
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes \
python -m pytest tests/destructive/test_project_mutation_sandbox.py tests/destructive/test_soundbank_audio_sandbox.py -q
```

Destructive tests must only mutate copied sandboxes under `WWISE_SANDBOX_ROOT`. Never point `WWISE_FIXTURE_PROJECT` at a source project, production project, user project, or any `.wproj` outside the active sandbox root.

### Keep-on-failure evidence workflow

```bash
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
WWISE_SANDBOX_KEEP_ON_FAILURE=1 \
WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes \
python -m pytest tests/destructive/test_project_mutation_sandbox.py -q
```

When a destructive sandbox fails and `WWISE_SANDBOX_KEEP_ON_FAILURE=1` is set, inspect the preserved sandbox and evidence under `.sisyphus/evidence/wwise-waapi-live-sandbox-coverage/`. Compare copied `.wproj`, `.wwu`, generated bank, audio, and log artifacts there. Do not commit preserved sandboxes, generated banks, generated audio, runtime logs, caches, `.venv`, or auth/session state.

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
- `WWISE_SANDBOX_ROOT`: root directory for copied sandbox projects. The default project runtime path is `.sisyphus/runtime/wwise-waapi-sandboxes`.
- `WWISE_SANDBOX_KEEP_ON_FAILURE`: set to `1` to preserve a failing sandbox and evidence for inspection. Leave unset for normal cleanup.
- `WWISE_LIVE`: set to `1` to opt into live Wwise prerequisite and read-only sandbox suites.
- `WWISE_DESTRUCTIVE`: set to `1` together with `WWISE_LIVE=1` to opt into copied-sandbox mutation suites. It has no destructive effect without the live gate.

## Rerunning failed category suites

Rerun only the failed category after the prerequisite smoke test passes. Keep the same env contract so evidence remains comparable.

```bash
WWISE_LIVE=1 WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject python -m pytest tests/live/test_waql_live_matrix.py -q
WWISE_LIVE=1 WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject python -m pytest tests/live/test_profiler_transport_soundengine.py -q
WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes python -m pytest tests/destructive/test_soundbank_audio_sandbox.py -q
```

Accepted WAAPI calls alone are not coverage. Promotion requires bounded readback, topic payload, profiler payload, generated artifact, or cleanup evidence that matches the category contract.
