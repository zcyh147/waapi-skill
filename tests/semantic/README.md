# Semantic OpenCode validation

Phase 3 semantic validation checks how the `waapi-skill` behaves inside an OpenCode workspace. It is separate from unit tests: mocked pytest is CI-safe, but it is not a replacement for real WwiseConsole semantic validation.

## Required live commands

Run the required 2022.1 semantic batch with live Wwise and OpenCode evidence:

```bash
python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test --scenario-set phase3-required --wwise-version 2022.1 --archive-root .sisyphus/evidence/waapi-opencode-semantic-runs --require-live
```

Run the all-version smoke batch, preferring live execution where prerequisites are present:

```bash
python tests/semantic/run_opencode_semantic_batch.py --workspace /Users/xiye/Documents/Git/waapi_skill_test --scenario-set phase3-smoke --wwise-version all --archive-root .sisyphus/evidence/waapi-opencode-semantic-runs --prefer-live
```

## Environment and workspace expectations

- The workspace must be `/Users/xiye/Documents/Git/waapi_skill_test` unless the command is intentionally pointed elsewhere.
- The workspace install at `.agents/skills/waapi-skill` must be a symlink to this repository's `skills/waapi-skill`; copied skill directories are rejected to prevent stale validation.
- Live runs require an executable version-specific `WwiseConsole.sh`, a matching `tests/_org/<version>/SampleProject.wproj`, OpenCode CLI access, and WAAPI readiness through the sandbox launcher.
- The required batch uses `--require-live`. Missing prerequisites or failed live attachment produce `blocked` records and a non-zero exit.
- The smoke batch uses `--prefer-live`. Versions without live prerequisites produce explicit `skip` records instead of silently disappearing; available-version live failures or semantic `fail` verdicts still produce a non-zero exit.
- A semantic scenario that runs and violates assertions records `fail`. A scenario that runs and meets assertions records `pass`.

## Archives and evidence

- Semantic archives are written under `.sisyphus/evidence/waapi-opencode-semantic-runs` by default.
- Archives are local and untracked by default because `.sisyphus/` is ignored.
- Archive records reference sandbox metadata, dispatcher evidence, command lines, OpenCode session ids, output, status, and failure notes. They do not copy sandboxes, full OpenCode databases, caches, virtual environments, or wholesale logs.
- Current live Task 10 evidence for the required 2022.1 semantic batch passes with `pass: 6`, `fail: 0`, `blocked: 0`, and `skip: 0` in `.sisyphus/evidence/task-10-live-2022-semantic-batch.json`.
- Current all-version smoke evidence is also accounted for with `pass: 10`, `fail: 0`, `blocked: 0`, and `skip: 0` in `.sisyphus/evidence/task-10-multiversion-smoke.json`.

## Mocked and nonlive checks

The Python tests for the semantic harness, archive writer, and scenario evaluator are CI-safe. They validate command construction, archive schema, verdict handling, and mocked/nonlive behavior. They don't prove that a real WwiseConsole semantic batch passed.

Useful regression commands:

```bash
python -m pytest tests/semantic/test_docs_semantic_inventory.py -q
python -m pytest tests/semantic/test_opencode_harness.py tests/semantic/test_semantic_archive.py -q
```

## Anti-drift policy

Phase 3 is a semantic validation layer. It avoids a full executor rewrite, schema stuffing, profiler overbuild, broad docs churn, and silent retargeting. Documentation should describe how to run and interpret the semantic batches; it must not become an implementation substitute.
