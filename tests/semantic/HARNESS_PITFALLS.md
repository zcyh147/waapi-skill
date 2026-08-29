# Fresh Agent harness pitfalls

Use this ledger when a Fresh campaign blocks before Codex, fails after an
accepted Gateway command, differs by host, or repeats a failure family below.
`tests/AGENTS.md` owns the rules. This file records signals, causes, and
prevention checks that are expensive to rediscover.

## Classify the failing layer first

| Evidence signal | Classification | Next action |
| --- | --- | --- |
| No Codex turn and no Broker record | launcher or campaign preflight | Repair the prerequisite, freeze the root, and open a new root. |
| Authenticated Broker rejection before runner dispatch | Agent command or Broker allow-list | Compare exact argv with the reviewed protocol; keep identities and paths exact. |
| Broker `accepted=true`, runner exit 0, Broker exit 125 | Broker response validator | Reproduce the exact payload-validation invariant without Codex. |
| Broker and reconciliation pass but an outcome gate fails | grader or final-response semantics | Inspect the named gate and raw Codex command facts. |
| Wwise dispatch or verification fails | production/runtime semantics | Preserve the sandbox and diagnose the matching real boundary. |

## Incident ledger

### Windows Session 0 process initialization

- Symptom: standalone Codex or `pwsh` exits with `0xC0000142` when a formal
  Fresh campaign starts directly through SSH.
- Cause: the formal Agent ran from SSH Session 0 instead of the logged-in
  desktop session.
- Prevention: SSH creates, starts, waits for, reads, and removes one temporary
  Scheduled Task. Its exported XML says `InteractiveToken`; its principal says
  `Limited`; the same numeric console session owns `explorer.exe`. Ordinary
  pytest and `ci/test.bat` remain direct SSH commands.

### Scheduled Task `Ready` is not campaign completion

- Symptom: Task Scheduler reports `Ready` while token-owned Codex/Python
  descendants or an unsealed attempt remain.
- Cause: the action shell exited before all descendants and evidence writers.
- Prevention: after `Ready`, use a fresh generic process query whose own path
  omits the campaign token. Require zero matching descendants plus the sealed
  summary and attempt manifest before unregistering the task.

### Windows task registration guessed the desktop environment

- Evidence: #96 query `r6` launcher probes stopped before campaign-root
  creation when the cmdlet rejected `InteractiveToken`, SSH reported
  `USERDOMAIN=WORKGROUP`, and a clean worktree lacked its ignored live config.
  A direct Python task action then returned code 2 without useful task output.
- Cause: Task Scheduler XML names the logon type `InteractiveToken`, while
  `New-ScheduledTaskPrincipal` spells the enum `Interactive`; SSH environment
  identity and a Git worktree are not the logged-on desktop identity or the
  machine-local test configuration.
- Prevention: obtain `UserId` from `Win32_ComputerSystem.UserName`, register
  `-LogonType Interactive -RunLevel Limited`, and attest `InteractiveToken` in
  exported XML. Task Scheduler may omit the default `RunLevel` element from
  that XML; attest `Limited` from the registered task Principal instead of
  treating the omitted XML tag as a launch failure. Before registration,
  require the candidate-local Python,
  absolute campaign path, action script, and copied ignored
  `live-environment.json` for a live profile. For a genuinely offline profile,
  pass the sealed `--offline-only` option on both hosts instead of requiring or
  copying live configuration. Run the original campaign inside a profile-free
  PowerShell action wrapper that records stdout, stderr, and exit code; SSH only
  registers, starts, polls, reads, and removes it.

### macOS foreground ownership and TCC

- Symptom: a unified shell receives `SIGTERM`, a `nohup` child outlives its
  attempt, or a background shell under `Documents` triggers TCC.
- Cause: the formal campaign lacks a one-shot user LaunchAgent, or its program
  routes through a protected temporary shell script.
- Prevention: put the exact Skill-local Python and campaign argv directly in a
  `RunAtLoad=true`, `KeepAlive=false` LaunchAgent. Prove one run, sealed output,
  and zero scoped processes, then boot it out.

### Compound Draft topology assumed one terminal per Draft

- Evidence: #83 Fresh `r1` on both hosts blocked before Codex with
  `each typed Draft flow requires exactly one terminal command`.
- Cause: the Broker assumed every child Draft ends in Preview or cancel. A
  compound parent consumes children after `draft-check` and owns the Preview.
- Prevention: require every child to finish checked, consume every child
  capability once, and allow exactly one parent Preview. Removing a child
  check is a focused negative.

### Optional discovery became one mandatory first command

- Evidence: #83 `r2` rejected direct `operation-schema waapi.undoGroup`; `r3`
  rejected one initial `operations` read.
- Cause: the Skill legally permits either direct schema lookup when the exact
  name is visible or one compact operation discovery when it is not.
- Prevention: accept exactly those two openings. Bind the optional branch to
  the exact `waapi.undoGroup` schema. Repeated, late, or differently bound
  discovery remains terminal.

### The archive validator inferred optional protocol from task policy

- Evidence: #96 query `r5` completed the reviewed query and produced a passing
  task result on both hosts, but the outer campaign reclassified each unit as
  BLOCKED because the valid terminal prefixes were `[1, 2]` rather than the
  older hard-coded `[1]`.
- Cause: task execution correctly sealed an optional `query-schema` protocol,
  while archive validation guessed optionality from project modification policy
  and knew only the older single-step read protocol.
- Prevention: derive optionality and accepted terminal prefixes from the sealed
  prompt protocol, never from unit metadata or a fixed prefix. Provisionally
  accept the optional result keys only until the seal is loaded, then require an
  exact match and reject missing, shortened, reordered, or invented prefixes.
  When the first `query-schema` is omitted from a multi-step repair protocol,
  replay the sealed lane with exactly that first step removed; do not truncate
  the full four-step list to its first three entries. #96 query `r11` produced a
  task-level PASS with `ambiguous-kind`, `refined-kind`, and the main query, but
  exposed this second archive-only failure before the omission-aware replay was
  covered by a synthetic regression. The same repair also has one primary
  business query but two audited `object.get` dispatches: the exact-type
  confirmation and the main query. Preserve those as separate counts in the
  runner and archive validator; auxiliary repair evidence must neither inflate
  business-oracle cardinality nor be rejected by a primary-only audit check.

### Interleaved Drafts leaked the most recent flow

- Evidence: #83 `r4` rejected the correct parent revision `1`; `r5` accepted
  the parent declaration in Gateway and then rejected its response as belonging
  to the second child.
- Cause: revision and payload validators used the most recent Draft receipt or
  `draft-start` instead of the command's owning Draft.
- Prevention: resolve revision binding, response ownership, read-only
  classification, and Preview replay from the step's exact first
  `/draft/draft_id` binding. Only receipts with the same `draft_id` advance that
  flow. Cover parent plus two interleaved children, wrong identity, stale
  revision, and same-Draft dependency-ready reordering.

### A clean candidate clone lacked its Skill-local runtime

- Evidence: #83 Windows `r6` completed all 15 Broker steps and one compound
  Preview, but its first Gateway output contained pip installation logs before
  JSON and failed exact-output grading.
- Cause: the campaign used another clone's interpreter while the candidate's
  `skills/waapi-skill/.venv` did not exist. Its first task-local `run.py`
  invocation auto-bootstrapped dependencies.
- Prevention: run the candidate's `scripts/setup_environment.py`, then launch
  with that candidate's `.venv` interpreter. Formal campaign preflight rejects
  a missing or different interpreter before creating a root or starting Codex.
  Independently, `run.py` owns a machine-readable stdout contract: any automatic
  bootstrap progress, pip output, and venv-path receipt is redirected to stderr.
  `test_run_bootstrap_if_needed_invokes_setup_when_venv_missing` seals that
  invariant so a clean ordinary real-test worktree cannot prefix Gateway JSON.

### A clean Windows pytest worktree selected the Store Python alias

- Symptom: direct-SSH `ci\test.bat` stops before pytest with Python exit `9009`,
  or creates an empty Poetry environment and then reports `No module named pytest`.
- Cause: the SSH `PATH` resolves the disabled Microsoft Store app-execution
  alias before the installed Python, and a new worktree has a distinct Poetry
  environment whose locked dependencies have not been installed.
- Prevention: for ordinary pytest only, prepend the known installed Python
  directory to that SSH process, create the worktree-local environment with
  `POETRY_KEYRING_ENABLED=false` and a null keyring backend, then run
  `ci\test.bat` directly through SSH. This is not a Fresh campaign and does not
  use Task Scheduler. Require the test-context header before counting an
  attempt; launcher failures receive no test result or retry number. From Git
  Bash, invoke the batch file through `cmd.exe //d //s //c`; `/c` may be path-
  converted into an interactive prompt and must not receive test credit.

### `pwsh -File -` over SSH echoed a script without executing it

- Symptom: the SSH command returned zero after printing only `PS ...>` and
  continuation `>>` prompts; there was no candidate attestation, test-context
  header, pytest output, or post-run status.
- Cause: on the fusion-win11 OpenSSH/Git-Bash chain, `pwsh.exe -File -` consumed
  standard input as an interactive session. A multiline block remained at the
  continuation prompt until EOF, and the shell exit code did not prove that
  the script body ran.
- Prevention: copy one bounded, profile-free `.ps1` to a temporary Windows
  path, execute its absolute path with
  `pwsh.exe -NoProfile -NonInteractive -File <path>`, require both the exact
  candidate hash and `== Test Context ==` before credit, then remove the
  temporary script. Stdin echo, prompts, or exit zero alone are zero test
  attempts.

### A rejected runner path can be a real Agent error

- Evidence: #83 macOS `r6` used the correct candidate runner for six commands,
  then changed it to a different nonexistent repository spelling.
- Cause: the Agent reconstructed an absolute path instead of reusing the
  visible exact locator.
- Prevention: keep the Broker's exact runner allow-list. Freeze the semantic
  failure; do not normalize or accept a near path. A Gateway-supplied
  continuation mismatch remains subject to its separate byte-exact audit.

### A natural business synonym can expose a real public-seam gap

- Evidence: #96 query `r10` on both hosts completed the live
  `Music` → `MusicSegment` clarification, then submitted the otherwise exact
  `CombatMix` query with `kind-is sound`. The Broker rejected it because the
  sealed oracle used `all-sounds`.
- Cause: `sound` and `all-sounds` express the same Gateway-level business
  meaning, but only the latter was public. The nearby Skill examples also used
  `sound-sfx` for a request whose oracle intentionally included SFX and Voice,
  so the reference and formal business meaning disagreed.
- Prevention: define any accepted synonym explicitly at the public Gateway,
  disclose its exact canonical meaning, and apply the same narrow
  canonicalization in the Broker before semantic comparison. Keep distinct
  meanings such as `sound-sfx` and `sound-voice` non-equivalent. Audit reference
  examples against the oracle before spending a new Fresh root; do not solve a
  stable vocabulary seam by repeatedly strengthening only the prompt.

### An optional business field can retain a non-neutral native default

- Evidence: #84 native-Windows Core Fresh root `iwin-core-33f668f-r13`
  followed `operations`, `request-schema`, and `draft-start`, then omitted the
  explicit `auto_check_out=false` requested by the user. The authenticated
  Broker rejected the incomplete declaration before Gateway or Wwise dispatch;
  the root is frozen without replay and no mutation occurred.
- Cause: the public field was correctly optional when the user says nothing,
  but its schema did not disclose that omission preserves Wwise's native
  `true` default. The Agent treated omission as equivalent to the explicit
  negative business intent even though their effects differ.
- Prevention: for an optional business field with a non-neutral native
  default, disclose structured `omitted_effect`, true/false effects, and an
  exact intent-binding rule in the Gateway contract. Keep the Broker strict:
  an explicit user value must survive into the closed business declaration.
  Do not weaken the oracle or retry the same root merely because a missing
  field resembles a safe default.

### Real-test helpers can outlive a public Gateway cutover

- Evidence: the first two #84 dual-host real attempts completed the new
  `core-call object.diff` and Core Business Draft `object.pasteProperties`
  dispatches, then failed only in test assertions and cleanup. The helper first
  required terminal state `verified` although the sealed verifier was
  deliberately `result_schema_checked`; after that correction it still used
  the retired `query-object --object-id ... --return-field ...` grammar from
  before #96.
- Cause: the product seam and deterministic tests migrated together, but a
  destructive-only helper was skipped by Program/Non-live and retained both an
  obsolete terminal-state assumption and obsolete query flags.
- Prevention: before spending a real-host rerun, audit the selected test node's
  setup, assertions, manual readback, and `finally` cleanup against the current
  `query-schema` or returned continuation. Exact-ID reads use
  `query-object --exact-id`; identity fields are default output and extra
  business fields use `--include`. Assert the sealed verifier terminal state
  instead of upgrading `result_schema_checked` to business verification. A run
  that reached Wwise but failed these test-only checks remains FAIL and receives
  no semantic or real-host PASS credit.
- Later #84 attempts also proved why that weak boundary matters:
  `pasteProperties` returned a schema-valid success on both Wwise versions, but
  neither omitted nor explicit `Notes` inclusion copied Notes. Do not wrap that
  no-op as a business capability; Notes remains reachable through
  `object.setNotes`. Real paste effect proof uses a live-discovered `Volume`
  Field Handle and reads `volume-db` back. A valid result alone is never
  upgraded to business success.

### Raw Core Drafts have two intentional operation identities

- Evidence: #84 Fresh root `imac-core-91a2adf-r1` was BLOCKED before Codex
  because the Broker required the Preview witness operation to equal the
  `draft-start` argument. The same preflight also classified
  `draft-declare-core-plan` as an interrupting non-Draft command.
- Cause: a reviewed raw Core Draft starts with the exact `ak.wwise.core.*` URI,
  while its immutable internal request is canonical `waapi.call` with that URI
  in `arguments.api`. The semantic Draft taxonomy predated this declaration.
- Prevention: accept either a named Business Adapter request whose operation
  equals `draft-start`, or canonical `waapi.call` whose exact `arguments.api`
  equals the raw Core start URI; no other mismatch is valid. Keep
  `draft-declare-core-plan` in the one shared Draft command taxonomy and run the
  complete protocol validator before spending a Fresh root. A pre-Codex block
  is frozen without replay or PASS credit.

### A Draft continuation must not require an ordinary query

- Evidence: #86 roots `imac-pset-7c222be-r1` and
  `iwin-pset-7c222be-r1` both started the Game Parameter Draft, then followed
  its instruction that a name-only target required `query-object` before an ID
  binding. The Broker correctly rejected that read as an interrupting non-Draft
  command. Both roots are semantic FAILs and receive no replay or PASS credit.
- Cause: `request-schema` made `draft-start` the exact continuation, while the
  resulting object-binding continuation disclosed only ID and complete-path
  routes and described a normal query as the name-resolution path. Those two
  instructions could not be completed in one uninterrupted Draft.
- Prevention: every natural business identity needed after `draft-start` must
  have a copy-ready Draft-local binding route. For globally typed names, fix the
  Wwise type in the continuation and let `draft-bind-object --exact-type-name`
  resolve at most two rows and accept exactly one. Keep ordinary reads outside
  an active Draft; run the complete protocol validator before a Fresh root.
- Follow-up: repaired roots `imac-pset-e1eed9d-r2` and
  `iwin-pset-e1eed9d-r2` copied and authenticated that exact typed-name command,
  but the offline business WAAPI shim recognized only the older
  `from search ...` unique-name form and returned no rows for the production
  `from type ... where name ... take 2` request. Keep the shared shim aligned
  with every production read shape exercised by offline Fresh profiles, and
  prove each added shape directly against its profile fixture before starting
  another Fresh root.

### Natural raw-API prompts need one bounded operation discovery

- Evidence: #84 Fresh root `imac-core-5a1d501-r2` failed semantically because
  the Agent correctly asked `operations` how to route “save the project”, while
  the synthetic Broker expected the opaque Core URI immediately. The prompt
  intentionally contained no URI or Gateway mechanics.
- Cause: the profile tested natural-language routing but omitted the shared
  one-read discovery allowance already used by other business profiles. Root
  `imac-core-0120163-r3` then exposed that the allowance itself accepted only
  named `operation-schema`, not the raw-API `request-schema` seam.
- Prevention: when a natural prompt cannot name its reviewed raw API, bind one
  optional initial `operations` read to that exact API. The Broker may insert
  it once before the exact first `operation-schema` or `request-schema`; any
  different, repeated, or later discovery remains a semantic failure. Freeze
  each original root without replay or PASS credit.

### Offline business mode must survive every campaign layer

- Evidence: #84 macOS r5/Windows r6 were rejected by the CLI parser, then
  macOS r6/Windows r7 reached the heavy-campaign guard and were rejected there;
  none created a campaign root or started Codex.
- Cause: the matrix already classified these profiles as offline production
  Gateway runs, but argument parsing, immutable heavy options, child argv, and
  live-config fingerprinting still hard-coded real-Wwise mode.
- Prevention: allow `--offline-only` only for registered offline business
  profiles, preserve it through selection, child argv, run-config validation,
  and evidence seals, and mark a nonexistent live config explicitly unused.
  Keep ordinary heavy profiles fail-closed to real Wwise.

## New-root preflight

Complete every item before spending a Fresh turn:

1. Freeze a clean exact Git candidate and use a new root.
2. Prepare that candidate's Skill-local environment and launch with its own
   interpreter; require the fail-fast interpreter check to pass.
3. Run the focused Broker/grader regression for every prior failure family.
4. On macOS, prove no real Wwise or earlier Fresh owner overlaps, then use one
   LaunchAgent.
5. On Windows, prove the console desktop, Explorer session, `InteractiveToken`,
   `Limited`, standalone Codex, and attested PowerShell Core before task start.
6. Freeze every FAIL or BLOCKED root without replay. Replay only an all-PASS
   root with identical `--resume --verify-only` options.
