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

For the structured object-query lane, this gate proves the versioned
`waapi-skill.object-query/v1` request/schema contract, deterministic Python
compilation, exact fake dispatch, and fail-closed rejection. It does not prove
that a newly added WAQL construct executes successfully in Wwise; record that
only from the matching real read-only lane.

## New Wwise version checklist

For a new supported Wwise lane, validate the whole path rather than only adding
a version string:

1. Re-run version-matched reflection for functions, topics, schemas, and the
   required Authoring-only supplement; review URI substitutions as well as
   count changes.
2. Regenerate and validate the versioned manifest, inventory digests, deferred
   classifications, metadata index, and semantic/WAQL resources.
3. Classify changed routes by host and execution lane, then update the
   capability and execution registries, adapter and request-mapping registries,
   and native-surface policy where applicable. For structured Gateway
   operations, `skills/waapi-skill/wwise_waapi/operation_registry.py` is
   authoritative; a builder implementation by itself is not a public operation
   contract.
4. Review the default structured `query-schema` and the separately disclosed
   `query-schema --advanced` contract against the new reflection. Extend
   five-version Builder compiler goldens, advanced fixed-URI/final-cap tests,
   schema parity, UTF-8 byte/framing disclosure, request ceilings, and
   mutation-isolation negatives whenever either query layer changes. Native
   advanced syntax is accepted or rejected
   by the matching live Wwise version; program tests must not claim otherwise.
5. Run focused tests and extend `ci/test.sh --mode program` to prove the new
   supported-version matrix. Then run the matching smoke/live and destructive
   sandbox lanes sequentially.
6. Update README inventories and `tests/TEST_INVENTORY.md` only after the
   corresponding generation or run. Use a targeted fresh-Codex semantic case
   for changed routing or agent behavior; do not spend a broad semantic matrix
   on a schema-only addition.

## Local real-Wwise path config

For live/destructive/smoke/matrix modes, machine-specific paths can be stored in the untracked JSON file:

- `tests/fixtures/local/live-environment.json`

Start from the committed template:

- `tests/fixtures/local/live-environment.example.json`

Set `WWISE_TEST_CONFIG=/absolute/path/to/live-environment.json` to use a different file. Each version entry may define `wwise_console`, `sample_project`, and optional `sandbox_root`. Environment variables (`WWISE_CONSOLE`, `WWISE_SAMPLE_PROJECT_PATH`, `WWISE_SANDBOX_ROOT`) still override JSON values for one-off runs.

## Cross-platform path and process boundaries

Treat a path according to the namespace that owns it; never normalize an
unknown string by replacing slashes:

- Host filesystem paths must use `pathlib`. When a value may originate on a
  different platform, select `PureWindowsPath` or `PurePosixPath` from its
  validated lexical flavor before localizing it. Production WAAPI host paths
  go through `skills/waapi-skill/wwise_waapi/host_paths.py`; semantic-only host
  fixture paths use `tests/semantic/support/codex_host_paths.py`.
- Paths stored inside evidence archives are portable logical identities, not
  host paths. Parse and compare them through
  `tests/semantic/support/codex_archive_paths.py`; persist only its canonical
  POSIX spelling. Do not use host `Path` semantics or `replace("\\", "/")` to
  derive an archive identity.
- Wwise object hierarchy paths, JSON Pointers, WAQL expressions, URI strings,
  and similar domain values are not filesystem paths. Preserve their domain
  separators and validate them with the owning parser instead of `pathlib`.
- Model-facing subprocess tests on Windows must use
  `tests/support/platform_process.py`. Do not restore bare-PATH launch through
  `cmd.exe`, `COMSPEC`, `shell=True`, or a hand-built command line. The ordinary
  helper starts the attested Python and broker shim directly while keeping model
  argv as data; the narrower PowerShell transport proof accepts only an already
  attested absolute `pwsh.exe` and the canonical bounded model-command grammar.

Add focused POSIX, Windows-drive, and UNC cases whenever a shared path boundary
changes. At minimum cover case semantics, traversal, mixed separators, spaces,
Unicode, and shell metacharacters where the value can reach a subprocess.

## Strict real modes

`live`, `destructive`, `smoke`, and `matrix` are strict real modes. They set `WWISE_STRICT_REAL=1`, require an executable `WWISE_CONSOLE`, and require an existing `.wproj` at `WWISE_SAMPLE_PROJECT_PATH`. Missing WwiseConsole or SampleProject prerequisites fail before pytest execution instead of becoming soft skips.

Real live/destructive tests may require a complete `VerificationResult` and
may assert that every packaged verification assertion passed, but they must
not select a business check by the human-readable `assertion.name`. Display
names are diagnostics, not a stable contract: public operations can migrate to
stronger verifier kinds without preserving legacy wording. Prove business
effects from the execute payload, structured verification readbacks, or a
separate closed Gateway query against the sandbox. Unit tests for an individual
verifier may intentionally lock its assertion names; fixtures for retired
verifier kinds must say explicitly that they are legacy compatibility tests and
must not be cited as current public-operation coverage.

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

The focused `modification_policy_9` campaign is separate from those historical
v2 totals. Its sealed
`campaign-modification-policy-9-c7` run passed 9/9 Wwise 2022.1 tasks and all
15 turns using nine unique memory-isolated Codex Terra threads. It covered
three repetitions each of `read_only`, question-style `ask_before_changes`,
and same-turn `allow_changes`; all source-project hashes remained unchanged
and every sandbox was cleaned. The six authorized writes each verified seven
created objects through 46 passing business assertions. Preserve this exact
scope: it is policy-interaction evidence for that frozen c7 candidate, not
broad API, cross-version semantic coverage, or fresh evidence for later
structured-query and closed-selector changes.

The `integration_workflows_cross_version_6` profile is a separate integration
acceptance contract, not a per-API coverage profile. It contains three
prewritten multi-operation workflows, each run once on Wwise 2022.1 and once on
2025.1: six fresh memory-off Codex tasks, 20 user turns, and 12 separately
previewed transactions. Use the formal campaign runner with `gpt-5.6-terra`,
medium reasoning, and the default service tier. Cases and versions run
sequentially. Keep the first pass frozen, collect ordinary semantic failures,
then make one repair batch and start a new campaign root; stop early only for a
systemic harness, sandbox, evidence, or cleanup fault. These totals define the
planned profile.

Historical evidence is split across three frozen 2026-07-31 roots. Initial
`a12` passed the four Alarm/Harbor version units and failed both Weather units;
fresh `a20-int22-weather` and `a24-int25-weather` roots passed the repaired
Weather units. This is passing evidence for all six unique units across roots,
not one single-candidate 6/6 campaign. Passing sandboxes were cleaned, failed
sandboxes remain quarantined, and every lifecycle record reports unchanged
source-project full hash and mtime. Those campaigns predate the structured
`query-schema`/`query-object --request-json` migration, the separately
disclosed bounded advanced-WAQL layer, and the removal of raw WAQL mutation
selectors. Those V1 roots do not validate the newer routing contracts; keep
the historical integration result attached only to its migration-before
candidate. The V2 evidence below applies only to its exact workflow paths.

The natural-language prompt revision received a fresh 2026-08-03 campaign.
`campaign-integration-workflows-v1-terra-20260803-current-r1` passed five of
six units. The 2025.1 Alarm failed safely on turn one because the Agent added a
redundant exact-ID Action lookup after the Event children row had already
returned `ActionType` and `Target`; no mutation occurred. After a query-reference
repair clarified that `Target.id` is the next Sound identity, fresh roots
`r2-int25-alarm-action-hop` and `r3-int22-alarm-action-hop` passed the 2025.1
and 2022.1 Alarm units on the same repaired candidate. Both repair roots pass
`--resume --verify-only`. Weather and Harbor loaded only the unchanged operate
reference and passed for both versions in `r1`. This gives all six current
prompt units passing evidence across roots, not a single repaired-candidate
6/6 run. All eight lifecycle records preserve source hashes and mtimes;
passing sandboxes were cleaned and the failed sandbox remains quarantined.
Those V1 roots do not validate the newer V2 fixture, routing, or workflow
contracts.

The separate `integration_workflows_v2_cross_version_6` profile uses the fixed
`WAAPI Skill Integration V2` graph committed in the 2022.1 and 2025.1
`tests/_org` SampleProject sources. It schedules three workflows on both
versions: six fresh memory-off Codex tasks, 16 user turns, and eight separately
previewed transactions. Use only `gpt-5.6-terra`, medium reasoning, the default
service tier, and sequential execution. Every unit starts by copying the
committed source into a new owned sandbox; Wwise must never open the committed
fixture itself. The lifecycle records the source full-tree hash and project
mtime before and after each attempt, removes a passing sandbox, and seals and
quarantines a failed, blocked, retryable, or indeterminate one.

The completed 2026-08-03 V2 evidence is cumulative across frozen roots, not one
final-candidate 6/6 run. `r8` passed both Rifle units, `r12-2022` passed the
2022.1 Weapons unit, `r23-2022-footsteps` passed the 2022.1 Footsteps unit, and
`r24-2025-repairs` passed the 2025.1 Footsteps and Weapons units. All six unique
units therefore have passing evidence across those roots. Passing sandboxes
were removed; failed or blocked diagnostic sandboxes were sealed and
quarantined; every recorded source-project full hash and mtime remained
unchanged.

The committed v2 baseline manifests are maintenance evidence, not semantic
passes. To refresh one, first prepare and open an isolated copy with the normal
test lifecycle, then run the collector against that already-running copy:

```bash
skills/waapi-skill/.venv/bin/python \
  tests/maintenance/collect_integration_workflows_v2_baseline.py \
  --version 2022.1 \
  --live-project /absolute/path/to/sandbox/SampleProject.wproj \
  --write
```

The collector is preview-only without `--write`, accepts only an absolute
sandbox `.wproj`, and performs live reads exclusively through
`skills/waapi-skill/scripts/run.py gateway.py`. It does not launch Wwise,
mutate a project, or authorize opening either fixed source. Repeat with the
2025.1 sandbox separately. Historical `integration_workflows_cross_version_6`
(V1) evidence does not validate this V2 profile. The completed V2 roots prove
only the exact Rifle, Footsteps, and Weapons workflow paths; they grant no
per-API coverage credit and do not prove advanced WAQL or unrelated routes.

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

The current 2022.1 v3 selection is 326 scenarios for 142 APIs: 116 single-turn
scenarios and 210 cases using the preview/confirm protocol. Seventeen cases
require more than one separately previewed call, for 230 confirmation turns in
total. With one fresh memory-isolated Codex task per scenario, that means 326
fresh tasks and 556 user turns. The representative later-version increments add
74 / 27 / 17 tasks for 2023.1 / 2024.1 / 2025.1, so the complete reviewed
selection is 444 fresh tasks and 792 user turns. Every confirmation binds only
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
