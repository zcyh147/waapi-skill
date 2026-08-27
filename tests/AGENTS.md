# Test helper usage (`ci/test.sh`)

Use `ci/test.sh` to run project test modes with consistent environment setup. See `tests/TEST_INVENTORY.md` for the human test inventory.

Repository development tests run through Poetry behind `ci/test.sh`. Do not
install or run those developer dependencies from `skills/waapi-skill/.venv`.
That Skill-local environment is reserved for the packaged Skill runtime and
real semantic campaigns, keeping developer tooling separate from the minimal
user-facing environment.

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

Run formal gates directly so their process exit status remains authoritative.
Do not pipe `ci/test.sh` or `ci/test.bat` through `tee` unless the invoking
shell has an explicit fail-closed pipeline policy and the pytest-side status is
checked. Without `pipefail`, a pytest failure or `KeyboardInterrupt` can be
masked by `tee` returning zero; such a run is invalid evidence even when its
outer command reports success.

After interrupting `ci/test.sh`, prove that its exact `test_driver.py` / pytest
process group exited before starting another gate. An outer PTY interrupt can
end the command session while leaving that owned child group alive. Inspect
PID, parent, process-group ID, and command line; terminate only the exact stale
owned group. A run that overlapped a stale gate or a changing worktree is not
evidence and must be restarted from a stable candidate.

Freeze the exact Git candidate before starting a cross-host or Fresh Agent
attempt, and keep the worktree read-only until every selected host has sealed
its result. If HEAD or any candidate-owned file changes while a child process
is running, freeze that root as candidate-drift evidence with no PASS credit,
even when its raw semantic assertions passed. Start a new root only after the
candidate is clean and stable; never combine the drifting result with the new
candidate.

Candidate Skill immutability is source immutability, not a ban on interpreter
caches. Hash and compare the Skill tree with the same repository-declared
runtime exclusions used to make the detached task copy (`.venv`,
`__pycache__`, `.pytest_cache`, `.coverage`, and `.DS_Store`). Generated
bytecode or cache files therefore cannot create a false Agent-write failure,
while every non-excluded source or resource change still fails the gate.

Do not inspect or regenerate source-derived inventories while a Program or
Non-live pytest process is still running. Isolation tests may temporarily
rewrite packaged Gateway or Registry files and restore them during teardown;
an intermediate `git diff`, parser digest, continuation digest, or generated
inventory can therefore describe only the test fixture, not the candidate.
Wait for pytest to exit, confirm that no owned test process remains, and only
then read the worktree or regenerate sealed artifacts.

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
- Archived business-Draft replay preserves the public abstraction boundary.
  Only an Adapter that owns cleaned-file evidence may materialize its Preview
  from a sealed pre-cleanup witness. A request whose identities were bound from
  live project state must replay the sealed Draft state through the existing
  state directory. Never add raw GUIDs, Wwise paths, or native request fields to
  a public receipt merely to make offline replay easier.
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

On macOS, do not overlap a Fresh Agent campaign with any smoke, live, or
destructive pytest process, even when their campaign roots, sandboxes, ports,
or Wwise versions differ. Audiokinetic's wrappers share the
`Wwise2019x64` CrossOver bottle: one lane can switch or hold that bottle while
the other is starting, causing Broker prefix loss, a direct client that cannot
close, or a long `ConnectionRefusedError` readiness timeout. Before launching
the one-shot Fresh LaunchAgent, prove that no real-test driver, matching pytest,
WwiseConsole wrapper, or campaign process is active. If overlap is discovered,
freeze the affected roots without replay, let the already-running owner finish,
then clean only proved-idle bottle helpers before starting a new root.

WwiseConsole stdout/stderr is drained as UTF-8 with replacement for malformed
bytes. Keep that explicit decoder on Windows; the locale default can be GBK
and can terminate the drain thread on platform labels such as `Windows®`.

`ak.wwise.cli.executeLuaScript` can end the macOS WwiseConsole WAAPI transport
after one non-retry indeterminate result. Record that operation as a host
boundary and never retry it. A module-scoped destructive fixture may then shut
down the lost lifecycle and relaunch the same sandbox on the same sealed port
solely to restore infrastructure for later, different tests. Teardown must own
the replacement lifecycle; otherwise later cases inherit a dead endpoint or
the replacement process escapes cleanup. A later PASS is evidence only for its
own operation, never retroactive credit for the blocked CLI Lua call.

### SoundBank file-operation fixtures

Keep the file-authority sequence explicit in real SoundBank workflows. The
operation I/O root must own both the active sandbox project and every exact
input/output artifact, and the sandbox project must be saved and non-dirty
before each file-processing Preview. Copy the `project.save` continuation
returned by `request-schema`: 2022.1 returns a complete zero-input
`gateway_argv`, while 2025.1 returns an inline `gateway_argv_prefix` because
its save schema includes an optional source-control boolean.

Wwise 2022.1 has a real silent-effect boundary for SoundBank Definition rows:
an ordinary Event row using the official quoted-name form can return success
while leaving `getInclusions` empty on both macOS and native Windows. Use a
canonical GUID or supported uint32 Short ID in 2022.1 fixtures and require the
public route to reject name identities before dispatch. The same quoted-name
workflow has macOS real passing evidence on 2023.1, 2024.1, and 2025.1;
preserve this as a versioned contract rather than globally removing name
support.

The committed 2025.1 SampleProject contains a hash-pinned optional Auro
Headphone reference that makes otherwise valid SoundBank generation report a
`MissingPlugin` error. For a generate workflow, normalize only the private
sandbox copy before Wwise starts with
`WWISE_2025_SOUNDBANK_AURO_PROFILE` from
`tests/semantic/support/codex_project_prelaunch_v3.py`. Keep its project and
output roots under one case-owned parent, preserve the normalizer's hash
attestations, and clean that complete parent after the attempt. A hand-edited
source project or a verifier that ignores the generation error is invalid
evidence.

## Extra pytest args passthrough

Append pytest args after `--`:

- `ci/test.sh --version 2024.1 --mode live -- -k object_topics -q`
- `ci/test.sh --version all --mode matrix -- --collect-only -q`

## Matrix safety note

`--mode all` runs the non-live suite first, then `--mode matrix` with `--version all`. `--mode matrix` still runs supported versions sequentially. Do not run all versions in parallel.

## Fresh-Codex semantic suites and the 40 / 98 / 168 numbers

Before preparing a new formal Fresh root or diagnosing a repeated Broker,
launcher, interpreter, or evidence-classification failure, read
`tests/semantic/HARNESS_PITFALLS.md`. It is the incident ledger and preflight
checklist; this file remains the authoritative rule set.

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

The frozen v2 prompts and historical digests do not guarantee that their shared
fixture bootstrap still matches the current public Gateway vocabulary. If a
selected v2 root is blocked before Codex starts because runner-owned setup calls
a retired Gateway command, freeze that root as zero semantic PASS and preserve
its lifecycle evidence. Do not retry the root, edit `evals-v2.json`, or count
the runner failure as an Agent result. Use a current executable profile when
one owns the changed routing, or satisfy an issue's explicit `real or Agent`
evidence boundary with the proportional real-host lane.

### Native-Windows Fresh Agent isolation

Native Codex resolves the current user's `%USERPROFILE%\.agents\skills` through
the Windows user profile Known Folder. Disposable `HOME`, `USERPROFILE`, and
`CODEX_HOME` values do not by themselves hide that tree. Before each formal
Windows campaign, enumerate its direct regular `SKILL.md` files and seal exact
path-based `skills.config=[{path=...,enabled=false}]` session overrides into
both `codex debug prompt-input` and every `codex exec`/resume argv. The
task-local `.agents\skills\waapi-skill\SKILL.md` remains enabled and the prompt
audit must still prove that it is the only non-system Skill visible. Recompute
the sealed list for a new campaign root so a newly installed user Skill cannot
appear silently; never rename, delete, or modify the user's Skill tree.

Pass these TOML overrides as an argv list through the attested PowerShell Core
host with native argument mode `Standard` or `Windows`. Windows PowerShell 5
legacy native argument passing strips the embedded TOML quotes and is not a
valid isolation probe. Formal Fresh Agent work runs from the active desktop
user's Scheduled Task with `InteractiveToken` and `Limited`; SSH only creates,
starts, waits for, reads, and removes that task. Ordinary `ci\test.bat` and
pytest runs continue directly over SSH.

With PowerShell's ScheduledTasks cmdlets, pass `-LogonType Interactive` and
`-RunLevel Limited`; the registered task must then report `InteractiveToken`
in its exported XML and `Limited` in its Principal. Stop before launch if
either attestation differs.

Matching Authoring-UI tests require more than a listening WAAPI port. Create the
disposable SampleProject through the existing optional-plugin isolation
prelaunch, start Wwise Authoring in an `InteractiveToken` / `Limited` desktop
task, and require `getProjectInfo` to report the exact sandbox project before
dispatch. A first load may pause with `ak.wwise.locked` while the message box
states that the project cache was generated by an older Wwise version; inspect
the interactive desktop and click only that exact `OK` prompt, then repeat the
normal readiness checks. A listener, task state, or `getInfo` alone is not
project readiness. If there is no active desktop session, the exact modal
cannot be identified, or the exact sandbox path never becomes ready, stop as
BLOCKED and preserve the evidence rather than guessing or retrying a failed
root.

Treat Task Scheduler `Ready` as the action-shell state, not campaign
completion. A formal campaign can leave token-owned Python/Codex/Wwise
descendants running after the PowerShell action returns. After `Ready`, wait
for the exact campaign-root token to disappear from a fresh process query,
then require the sealed consolidated summary and attempt manifest. Run that
query from a generic profile-free `.ps1` whose own path omits the root token;
otherwise the checker can count itself. Only then unregister the task and
classify the root.

The unelevated Codex runner may transiently report
`CreateProcessAsUserW failed: 267` for an invalid working directory before
PowerShell starts, even after earlier commands in the same task succeeded. The
Skill permits exactly one identical replay of that complete shell command, and
the harness credits it only through `recoverable_preprocess_attempt_indexes`;
this is process-launch recovery inside one task, not a Gateway or campaign-root
retry. A second 267, a changed command, or an Agent that stops instead freezes
the root as infrastructure-blocked. Preserve the failed command index and exact
reported `cwd` in evidence; do not repair, resume, or rerun that failed root.
If the Agent itself repeats the command, retain both attempts: the later command
may reach the Broker successfully while the unit still fails its sealed command
count or copy-integrity contract. Record that as a semantic FAIL with a
pre-Broker infrastructure precursor, not as successful recovery and not as a
reason to retry the same root.

Do not match the literal English `Active` in `quser`: its state column is
localized. On `fusion-win11`, prove the desktop from a user-owned `console`
row plus an `explorer.exe` in that same numeric session, or use a locale-neutral
WTS connect-state check; otherwise stop as blocked. `Get-ScheduledTask` must
report Principal `RunLevel=Limited`, while exported XML must report
`LogonType=InteractiveToken`. Task Scheduler may omit the default
`<RunLevel>LeastPrivilege</RunLevel>` element, so absence of that optional XML
tag is not a failed Limited attestation.

On native Windows, a Gateway-owned v2 `model_command` must use the fixed
backslash task-local runner spelling. Do not emit the POSIX spelling and rely on
Broker path normalization: Fresh Agents otherwise reconstruct the familiar
Windows spelling instead of copying the continuation verbatim, and exact
continuation provenance is lost even when the resulting argv is equivalent.
Continuation grading must unwrap the attested host frame through the shared
command-record helper; never assume every recorded command is a three-token
POSIX `shell -lc <script>` wrapper when grading native Windows evidence.

Run the final scoped-process check from a separate SSH invocation after the
Scheduled Task reports `Ready`. A cleanup script whose own path contains the
campaign-root token also places that token in its parent `bash.exe` command
line; filtering only the current PowerShell PID therefore creates a false
residual-process match. Either exclude the complete checker ancestor chain or,
preferably, finish the checker and use a fresh read-only SSH process query.
Never kill a matching process until its exact PID, ancestry, and command line
prove that it belongs to the completed campaign rather than to the check itself.
Put a Windows process query that uses PowerShell `$variables` in a temporary
profile-free `.ps1`, copy and run it through SSH, then remove it. An inline
`-Command` can lose those variables across the SSH and shell layers. Filter by
the exact campaign-root token; existing Codex app-server or proxy processes
without that token are unrelated and remain untouched.

### macOS Fresh Agent launch ownership

A formal macOS campaign may outlive the Codex app's unified command session.
Do not use a long-lived unified command or `nohup`: the former may deliver
`SIGTERM`, while the latter can leave the child matrix running after the
top-level campaign process has disappeared, so the attempt never seals. A
matrix summary is not campaign evidence until the top-level attempt manifest
and digest exist.

Launch long macOS campaigns as a one-shot user LaunchAgent. Its temporary
plist must use the exact Skill-local Python campaign argv, the clean candidate
worktree as `WorkingDirectory`, `RunAtLoad=true`, and `KeepAlive=false`.
Put the Skill-local Python executable and complete campaign argv directly in
`ProgramArguments`; do not route the job through a temporary shell script under
`Documents`. A background `/bin/bash` can be denied that script by macOS TCC
before the campaign creates a root, even when the interactive Codex process can
read the same repository.
Validate the plist, bootstrap it in `gui/$(id -u)`, and require exactly one run
and exit code zero. Do not use `launchctl submit`: its generated job can relaunch
the same immutable root after a successful run. After completion, require the
sealed attempt manifest and digest, the expected consolidated result, and zero
scoped Codex/Wwise/campaign processes; then boot out the job and remove its
temporary plist. Freeze any interrupted or unsealed root without resume or
verify-only replay.

When macOS TCC denies a background process access to a candidate below
`Documents`, make a clean detached clone at a no-space path outside that
protected tree and prove its exact commit before launch. Prepare both runtime
layers there: `setup_environment.py` provides the packaged Skill/campaign
interpreter, while Poetry provides the repository smoke/readiness probes. Run
the matching real smoke lane from that exact clone before spending a Fresh
Agent attempt. If the selected fixture legitimately needs longer than the
default 60-second WAAPI readiness window, pass an explicit finite
`--wwise-readiness-timeout` on the campaign command (for example, `180`); the
campaign seals and forwards that value. Do not rely on an ambient environment
override or treat an unrecorded timeout increase as equivalent evidence.

On native Windows, a large project can spend several minutes enumerating
missing plug-ins before the WAAPI server becomes reachable. A launch may print
`Wwise Authoring API server started` only while the timed-out helper is already
collecting diagnostics; that late log line does not turn the frozen root into a
PASS. Preserve the BLOCKED root, confirm that its source hash and mtime are
unchanged and its scoped descendants are gone, then use a new root with a
larger explicit finite `--wwise-readiness-timeout` when the diagnostics prove
that project loading merely exceeded the sealed limit. Never resume or replay
the timed-out root, and never change the Skill, fixture, PATH, sandbox, or
failed unit to hide this infrastructure boundary.

The scoped residual-process check does not cover CrossOver bottle services
that reparent to PID 1. If macOS Wwise stays running but readiness times out
and its output stops at the bottle link or project-loading banner, first prove
that no WwiseConsole or Authoring project process is active, then count the
Audiokinetic `Wwise2019x64` Wine helpers (`wineserver`, `services.exe`,
`winedevice.exe`, `rpcss.exe`, and related bottle services). A large
cross-campaign residue is an infrastructure fault even when every campaign
root reports zero scoped processes. Terminate only that proved-idle
Audiokinetic bottle set, prove its helper count reaches zero, and require the
matching version's real smoke lane to pass before opening another Fresh root.
Never kill bottle helpers while a Wwise project process is active, and never
credit the cleanup or smoke as semantic PASS.

### Failure-first campaign scheduling

After a frozen full-profile root exposes ordinary semantic failures, repair the
shared deterministic causes before spending more Fresh Agent tokens. First run
tight non-live regressions for every prior failure family. A later formal root
may schedule those previously failing units first only when the selected full
profile, candidate, immutable options, and evidence root remain unchanged and
each selected unit still runs at most once. If the priority units pass, continue
the remaining units in that same root; do not rerun the priority units.

Do not combine targeted roots into a full-profile PASS. If the runner cannot
change priority without changing its sealed selection contract, keep the normal
full-profile order instead of adding a second campaign path. A failed root stays
frozen without verify-only replay; final acceptance still requires one complete
passing root per host followed by its identical verify-only audit.

### Multi-Draft Broker flow identity

Compound business protocols may keep one parent Draft alive while several child
Drafts are started, revised, checked, and then consumed. The semantic Broker
must resolve every revision binding, response projection, read-only
classification, and Preview replay through the command's exact owning
`draft-start` and `draft_id`. Never infer ownership from the most recently
started or most recently updated Draft. Same-Draft dependency-ready reordering
may use the latest prior receipt with that exact `draft_id`; a receipt from any
other Draft must remain invisible to the flow and cannot satisfy a stale
revision. Focused Broker regressions must cover an interleaved parent plus at
least two children, a wrong child/parent identity, a stale revision, and the
existing single-Draft reordering path before a new compound Fresh campaign is
opened.

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

The public `integration` profile is the integration-acceptance contract, not a
per-API coverage profile. It contains six prewritten multi-operation workflows,
each run once on Wwise 2022.1 and once on 2025.1: 12 fresh memory-off Codex
tasks, 36 user turns, and 20 separately previewed transactions. The workflows
are Weather, Alarm, Harbor, Rifle, Footsteps, and Weapons. Use the formal
campaign runner with `gpt-5.6-terra`, medium reasoning, and the default service
tier. Cases and versions run sequentially. The fixed committed baselines apply
only to Rifle, Footsteps, and Weapons. Keep the first pass frozen, collect
ordinary semantic failures, then make one repair batch and start a new campaign
root; stop early only for a systemic harness, sandbox, evidence, or cleanup
fault. These totals define the planned profile.

Run the public profile with the Skill-local interpreter and a new explicit
campaign root. Its default composed suite means callers do not pass `--suite`:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py \
  --profile integration \
  --model gpt-5.6-terra \
  --reasoning-effort medium \
  --service-tier default \
  --campaign-root skills/waapi-skill-workspace/campaign-integration-new-candidate-r1
```

The old `integration_workflows_cross_version_6` and
`integration_workflows_v2_cross_version_6` profile IDs remain internal
compatibility names for sealed history and replay. Never relabel their roots as
a unified `integration` campaign or a single-candidate 12/12 result.

The frozen public `integration` candidate
`7f54506783a131695bafb97b89103488cb73d96c` has host-specific cumulative
evidence, not one single-root pass. On macOS, `imac-int-7f54506-r1` passed 7
units and failed 5, `imac-int-7f54506-r2-retry5` passed 4 and failed 1, and
`imac-int-7f54506-r3-rifle` passed its one fresh Rifle unit and its identical
`--resume --verify-only` audit. All 12 unique public-profile units therefore
have macOS passing evidence across those three roots, but no root passed 12/12.

On native Windows, `iwin-int-7f54506-r1` passed 9 units and failed 3. Fresh
root `iwin-int-7f54506-r2-retry3` then passed Weather and failed both Weapons
units, leaving 10 of 12 unique public-profile units with native-Windows passing
evidence. Both remaining Weapons units failed in both roots when the
authenticated Broker rejected malformed preview JSON before the rejected
command reached the runner or Wwise; no mutation occurred. This is not complete
native-Windows `integration` acceptance and must not be reported as Windows
12/12. All four roots containing semantic FAILs were frozen without
verify-only replay. Independently,
`test_native_windows_powershell_shim_preserves_hostile_json` passed both native
Windows parameterizations (2 passed, exit 0), proving exact hostile-JSON
preservation through pwsh -> PS1 -> Broker without granting any semantic PASS
credit. On both hosts every source-project full hash and mtime remained
unchanged, passing sandboxes were removed, failed sandboxes were sealed and
quarantined, and no scoped residual process remained.

The frozen Composer public `integration` candidate
`198a510e49f1215b3c02f6d3108c734fc5c59400` has complete cumulative evidence
on both hosts, but neither host has a single-root 12/12 result. On macOS,
`imac-integration-198a510-r1` passed 11 units and failed INT22 Weather;
`imac-integration-198a510-r2-int22-weather`,
`imac-integration-198a510-r3-int22-weather`, and
`imac-integration-198a510-r4-int22-weather` each preserved one further
ordinary INT22 Weather FAIL,
while `imac-integration-198a510-r5-int22-weather` passed that unit fresh
and then passed identical `--resume --verify-only`. On native Windows,
`iwin-integration-198a510-r1` passed 6 and failed 6,
`iwin-integration-198a510-r2-retry6` passed 5 and failed INT25 Footsteps,
`iwin-integration-198a510-r3-footsteps` preserved another Footsteps FAIL, and
`iwin-integration-198a510-r4-footsteps` passed Footsteps fresh plus identical
verify-only. Thus all 12 unique public-profile units have PASS on the same
frozen Skill/harness candidate on each host, cumulatively across roots. Every
FAIL root was frozen without verify-only; every source full hash and project
mtime was unchanged, PASS sandboxes were removed, and FAIL sandboxes were
sealed/quarantined. Frozen-candidate development gates passed with focused
semantic 464 passed / 4 skipped, Program 2923 passed / 2 skipped, and Non-live
7763 passed / 104 skipped / 27 deselected. Native-Windows focused validation
passed 462 / skipped 6 POSIX-only cases. Commit
`030231b41e623e72f72de785d6bcbc3780d7eb37`
changes only domain/planning docs, one unit test, and the program manifest, so
it does not replace the frozen Skill, suite, runner, or semantic harness.

Composer migration evidence is focused Adapter evidence, not public
`integration` acceptance. For `object.set`, candidate
`68697244063e02304eea79da54da502270be3704` passed Weather and Weapons on
Wwise 2022.1/2025.1 in both macOS root `imac-flatrow-6869724-r1` and
native-Windows root `i15-6869724-r1`; both four-unit roots also passed
identical `--resume --verify-only` audits. For `audio.import`, macOS root
`imac-import-6479595-r13-final6` at
`6479595ea4b9a53c3351a4d1595c988e94ee5967` passed all six selected
Weather/Rifle/Footsteps version units fresh and verify-only. Native-Windows
root `iwin-import-f87b800-r2-interactive` passed four and failed two;
`iwin-import-0be8266-r3-rifle-footsteps` then passed Footsteps and failed
Rifle, and final fresh root `iwin-import-0be8266-r4-rifle` passed Rifle and
its identical verify-only audit. The commits after `6479595` changed only
program/semantic tests and harness support, not the packaged Skill tree. Thus
all six Windows audio-import units have passing evidence cumulatively across
three frozen roots, not one root or one Git candidate with a 6/6 result. Every
recorded source hash/mtime stayed unchanged; PASS sandboxes were removed, FAIL
sandboxes were sealed/quarantined, and scoped residual-process checks were
empty.

Historical macOS evidence is split across three frozen 2026-07-31 roots. Initial
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
The roots named in this paragraph and the 2026-08-03 macOS paragraph below
seal `runtime.platform=darwin`; later cross-host component reruns are recorded
separately.

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

Later reruns used the legacy internal
`integration_workflows_cross_version_6` component, not the public composed
`integration` profile. At commit
`9e75a1aea496abcb9ef2a61e1da685adb99f4b01`, macOS root
`imac-wah-9e75a1a-r1` passed all six component units fresh and passed
`--resume --verify-only`. At commit
`9b4de8f618855091a424700b50ab8b0fd1989270`, macOS root
`imac-wah-9b4de8f-r1` passed five units and failed one, and native-Windows root
`iwin-wah-9b4de8f-r1` passed three and failed three; both failed roots were
frozen without verify-only replay. These runs are exact legacy-component
provenance, not current `integration` acceptance and not unified 12/12 evidence.

The legacy internal `integration_workflows_v2_cross_version_6` component uses
the fixed `WAAPI Skill Integration V2` graph committed in the 2022.1 and 2025.1
`tests/_org` SampleProject sources. It schedules three workflows on both
versions: six fresh memory-off Codex tasks, 16 user turns, and eight separately
previewed transactions. Use only `gpt-5.6-terra`, medium reasoning, the default
service tier, and sequential execution. Every unit starts by copying the
committed source into a new owned sandbox; Wwise must never open the committed
fixture itself. The lifecycle records the source full-tree hash and project
mtime before and after each attempt, removes a passing sandbox, and seals and
quarantines a failed, blocked, retryable, or indeterminate one.

The completed 2026-08-03 macOS evidence for that legacy component is
cumulative across frozen roots, not one final-candidate 6/6 run. `r8` passed
both Rifle units, `r12-2022` passed the
2022.1 Weapons unit, `r23-2022-footsteps` passed the 2022.1 Footsteps unit, and
`r24-2025-repairs` passed the 2025.1 Footsteps and Weapons units. All six unique
units therefore have passing evidence across those roots. Passing sandboxes
were removed; failed or blocked diagnostic sandboxes were sealed and
quarantined; every recorded source-project full hash and mtime remained
unchanged.

The later native-Windows evidence for that legacy component is also cumulative.
Commit `0dfea2b` root
`windows-v2-six-0dfea2b-r1` attempted all six units, passed 2022.1 Rifle,
2022.1 Footsteps, and 2025.1 Rifle, failed the other three, exited `1`, and had
no verify-only replay. At `a516835`, `a516-w22-r1` passed 2022.1 Weapons fresh
and verify-only; `a516-f25-r1` failed 2025.1 Footsteps and was frozen without
verify-only. At `f1b6a51`, `f1b-f25-r1` and `f1b-w25-r1` passed 2025.1
Footsteps and Weapons fresh and verify-only. All six V2 units therefore have
native-Windows passing evidence across these frozen roots, but there is no
single-root or single-candidate Windows 6/6 result.

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
evidence does not validate this fixed-baseline component. The completed roots
prove only the exact Rifle, Footsteps, and Weapons workflow paths; they grant no
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
