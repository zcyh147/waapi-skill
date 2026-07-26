# Test helper usage (`ci/test.sh`)

Use `ci/test.sh` to run project test modes with consistent environment setup. See `tests/TEST_INVENTORY.md` for the human test inventory.

## Common commands

- `ci/test.sh --mode program`
- `ci/test.sh --mode nonlive`
- `ci/test.sh --version all --mode all -- -q -ra`
- `ci/test.sh --version all --mode matrix -- -q -ra`
- `ci/test.sh --version 2021.1 --mode live -- -q -ra`
- `ci/test.sh --version 2021.1 --mode destructive -- -q -ra`
- `ci/test.sh --version all --mode smoke`

Positional form is still supported, for example `ci/test.sh 2021.1 live`.

## Pure program gate

Use `ci/test.sh --mode program` for the five-version public-route expansion. This mode is deliberately narrower than `nonlive`: it selects only the packaged public-route coverage, program matrix, negative gateway contracts, isolated-I/O policy tests, optional registry-integrity test, and the generic transaction full-chain test under `tests/unit`.

The program gate forces `WWISE_LIVE=0`, `WWISE_DESTRUCTIVE=0`, and `WWISE_STRICT_REAL=0`; clears inherited Wwise executable, project, endpoint, and pytest-addopts settings; and uses injected fake clients. It never collects `tests/semantic`, `tests/live`, or `tests/destructive`, and it must not start Codex, WwiseConsole, or a network client.

Extra arguments after `--` may be pytest flags or filters such as `-q`, `-ra`, `--collect-only`, or `-k expression`. Additional test paths, node ids, `.py` files, and `--pyargs` are rejected so the fixed program-only collection cannot be widened accidentally.

## Local real-Wwise path config

For live/destructive/smoke/matrix modes, machine-specific paths can be stored in the untracked JSON file:

- `tests/fixtures/local/live-environment.json`

Start from the committed template:

- `tests/fixtures/local/live-environment.example.json`

Set `WWISE_TEST_CONFIG=/absolute/path/to/live-environment.json` to use a different file. Each version entry may define `wwise_console`, `sample_project`, and optional `sandbox_root`. Environment variables (`WWISE_CONSOLE`, `WWISE_SAMPLE_PROJECT_PATH`, `WWISE_SANDBOX_ROOT`) still override JSON values for one-off runs.

## Strict real modes

`live`, `destructive`, `smoke`, and `matrix` are strict real modes. They set `WWISE_STRICT_REAL=1`, require an executable `WWISE_CONSOLE`, and require an existing `.wproj` at `WWISE_SAMPLE_PROJECT_PATH`. Missing WwiseConsole or SampleProject prerequisites fail before pytest execution instead of becoming soft skips.

Real launches append proof to `.waapi-skill-state/evidence/waapi-test-remediation/real-wwise-launches.jsonl`. Check the audit with:

- `wc -l .waapi-skill-state/evidence/waapi-test-remediation/real-wwise-launches.jsonl`
- `tail -n 4 .waapi-skill-state/evidence/waapi-test-remediation/real-wwise-launches.jsonl`

Some committed capability and fixture rows retain `.sisyphus/evidence/...` as
the literal provenance of older validation runs. Those strings are historical
records, not an active output directory. Do not rewrite them to the current
state root unless the underlying evidence was actually migrated.

Audit rows include the pid, port, command, sandbox project, `getInfo` version proof, `ready_duration_seconds`, and cleanup result. `ready_duration_seconds` measures WAAPI readiness, not the total foreground GUI or plugin warning lifetime.

During WwiseConsole startup, repeated `ConnectionRefusedError` lines from WAAPI probes can be normal while Wwise loads the project, missing-plugin warnings, or WAAPI server listeners. Do not treat those probe errors as failure by themselves; judge the run by the final `smoke ok`/`getInfo` proof, `ReadinessTimeout`, or `EarlyProcessExit` diagnostics. For slow 2021.1 launches, `WWISE_READINESS_TIMEOUT=180` and optional `WWISE_WAAPI_PORT=<port>` are valid debugging overrides.

## Extra pytest args passthrough

Append pytest args after `--`:

- `ci/test.sh --version 2024.1 --mode live -- -k object_topics -q`
- `ci/test.sh --version all --mode matrix -- --collect-only -q`

## Matrix safety note

`--mode all` runs the non-live suite first, then `--mode matrix` with `--version all`. `--mode matrix` still runs supported versions sequentially. Do not run all versions in parallel.

## Fresh-Codex semantic suites and the 40 / 98 / 168 numbers

`skills/waapi-skill/evals/evals-v2.json` is the frozen historical semantic
suite. Its three profile names are also their exact fresh-Codex session totals:

- `screening` = 40 sessions. This is the small routing/safety sample.
- `formal_98` = 98 sessions. This adds repetition, especially for the seven
  historical offline boundary cases.
- `full_cross_version_168` = 168 sessions. This is the five-version v2 matrix,
  not 168 APIs and not 168 pytest functions.

Those numbers describe scheduled v2 sessions only. They are not proof that a
campaign completed, and they must not be reused as coverage totals for a newer
suite. A partial, quota-blocked, prerequisite-blocked, or interrupted campaign
is incomplete even if its selected profile is named `formal_98` or
`full_cross_version_168`.

The review-oriented v3 bundle is rooted at
`skills/waapi-skill/evals/suite-v3.json` and deliberately separates:

- `online_tests.json`: real, sandboxed Wwise WAAPI behavior tests;
- `offline_tests.json`: catalog, schema, version, and unsupported-interface
  questions that must not connect to Wwise.

V3 does not inherit the 40 / 98 / 168 totals. Its definition audit counts a
scenario for an API only when that API has a declared primary dispatch count and
effect plus an independent business-state oracle plan. This is review coverage,
not proof of an exact request predicate or an implemented oracle. Fixture setup,
cleanup, supporting readback, and repetitions do not receive coverage credit.
Keep `evals-v2.json` unchanged so historical campaign digests remain
verifiable. V3 definitions cover the five-version unique executable URI union,
not every version/API row. Most of that catalog remains review-only. The
approved `heavy_cross_version_80` subset is the exception: it has implemented
adapters and sealed real-Wwise evidence for 70 cases on 2022.1, five on 2024.1,
and five on 2025.1. Do not extrapolate those 80 results to the remaining V3
catalog or to every version/API row.

The current 2022.1 v3 selection is 316 scenarios for 137 APIs: 110 single-turn
scenarios and 206 cases using the preview/confirm protocol. Seventeen cases
require more than one separately previewed call, for 226 confirmation turns in
total. With one fresh memory-isolated Codex task per scenario, that means 316
fresh tasks and 542 user turns. The representative later-version increments add
66 / 25 / 17 tasks for 2023.1 / 2024.1 / 2025.1, so the complete reviewed
selection is 424 fresh tasks and 762 user turns. Every confirmation binds only
the currently visible immutable preview. Do not describe this as a
dozens-of-conversations run or silently combine APIs to reduce the total;
changing that cost model requires reviewed composite cases with their own
business assertions.

`adapter_registry.json` currently closes every fixture, trigger, oracle, and
cleanup identifier used by the definitions, but its status is
`specification_only_pending_user_review`. These identifiers are not executable
implementations. After prompt approval, implement them through the existing
fresh-Codex campaign/matrix lane; do not introduce a second semantic harness.
The implementation must also replace every dispatch's prose effect with a
closed args/options predicate derived from runner-owned visible inputs and the
versioned schema before any case can be called executable.

`request_mapping_registry.json` is a separate fail-closed readiness list. Its
current audit blocks 35 scenario definitions across 21 APIs whose natural
terms, structured values, or requested route cannot yet be mapped from the
packaged versioned resources. A blocked scenario still counts as a reviewable
prompt/assertion definition, but it must not enter a real campaign or be called
runnable. Close these entries with a versioned resource or deterministic
builder; never teach the model to guess enum integers or unresolved tokens.

For a user-approved v3 real campaign, freeze the Skill, definitions, adapters,
runner, model settings, and source-project digest before the first case. Run
cases sequentially. Every case starts from a new scenario-owned project copy
and scenario-owned asset/output directory; a successful case closes Wwise and
removes all owned state, while a failed or indeterminate case is sealed for
evidence and is never reused. Do not patch the Skill or definitions between
ordinary case failures: finish the frozen pass, consolidate isolated failures,
then make one reviewed repair batch and start a new campaign root. Abort the
pass immediately only for a systemic harness, source-sandbox, or cleanup fault
that could invalidate later cases.

The 2022.1 heavy `ak.wwise.cli.generateSoundbank` runner performs one additional
runner-owned normalization on each private copy before Wwise starts. It removes
only identity-pinned optional plug-in objects, archives the exact-hash McDSP
Work Unit below the case I/O root, proves retained Porsche and built-in EQ
anchors, and records a structured prelaunch report. Its separate business host
is copied from that normalized pre-setup tree. This is test-fixture hygiene,
not Skill behavior, a modification of the immutable SampleProject, or evidence
that third-party plug-ins are supported. Never reproduce it in a user's Wwise
project or count a direct WwiseConsole diagnostic as semantic campaign proof.
