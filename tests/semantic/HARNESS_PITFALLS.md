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

### Windows SSH verify-only still needs the sealed standalone Codex path

- Evidence: after native-Windows root `iwin-runtime-114e948-r4` passed fresh in
  an active-desktop task, a direct SSH `--resume --verify-only` invocation
  stopped with exit 2 before reading the root because Session 0 did not discover
  the standalone Codex executable. The identical verify-only command with the
  exact `codex_binary` sealed by that root exited 0; it started neither Codex nor
  Wwise and changed no evidence.
- Cause: verify-only does not execute a new Agent turn, but campaign preflight
  still resolves and attests the configured Codex binary. User-owned standalone
  install locations visible to the interactive task are not necessarily
  discoverable from SSH Session 0.
- Prevention: read the exact absolute `codex_binary` from the sealed campaign
  configuration and pass it back through `--codex-binary` for direct-SSH
  verify-only. Treat discovery failure as a launcher diagnostic, not a semantic
  retry, and still require zero root-token processes plus the unchanged sealed
  attempt manifest.

### Do not overlap a formal Windows Fresh root with unrelated long Codex work

- Evidence: exact candidate `f8968f7` root `iwin-runtime-f8968f7-r2` ran in an
  attested active-desktop `InteractiveToken` / `Limited` task, created a fresh
  thread, then timed out after 241 seconds with one progress reply, zero Skill
  reads, zero commands, zero Broker records, and zero Wwise dispatch. Frozen
  root `iwin-runtime-f8968f7-r3` increased only the sealed Codex timeout to 600
  seconds; after 445 seconds Codex exited zero but reported that its first
  required Skill read had not returned. It likewise produced zero completed
  commands or Broker records. Both roots sealed `BLOCKED`, started no Wwise,
  changed no workspace file, and ended with zero scoped process/task residue.
- Concurrent state: the same desktop was running a separate long-lived Codex
  development/test workflow using Wwise Console and REAPER. A read-only host
  snapshot showed moderate rather than exhausted CPU/memory, so this does not
  prove local resource starvation; it does prove that a larger Fresh timeout
  alone is not a repair.
- Prevention: when the user has disclosed another long Codex workflow on the
  same Windows desktop, postpone the formal Fresh root until that workflow is
  idle. macOS and Windows campaigns may still run in parallel with each other.
  Do not keep increasing the timeout or opening new roots after the same
  pre-Skill-read stall repeats; freeze the evidence, remove the task, and keep
  product/deterministic work moving on the other host.

### A permitted Windows 267 retry is one effective Gateway command

- Evidence: #86 Windows root `iwin-pset-98d9e70-r4` passed every Broker,
  Preview, closed-request, and final-response gate. One `request-schema` shell
  launch failed before PowerShell with `CreateProcessAsUserW failed: 267`, then
  the Agent followed the Skill's one-time identical retry rule and succeeded.
  Reconciliation nevertheless counted both records and failed 8 commands
  against 7 Broker dispatches.
- Cause: command classification already excluded the proven pre-process 267
  attempt, but V3 Gateway argv extraction scanned raw command records again.
- Prevention: both candidate argv and raw-record extraction remove only indexes
  accepted by `recoverable_preprocess_attempt_indexes`: failed before shell,
  exact Windows PowerShell provenance, adjacent identical command and argv, and
  a successful 0/2 successor. Never collapse a non-267, changed, non-adjacent,
  or twice-failed command.
- Follow-up: `iwin-pset-81aeb6e-r5` then passed Broker, reconciliation,
  Preview, closed-request, and final-response gates, but the shared Business
  runner's unexpected-command cardinality still counted the same excluded 267
  record. Every command-cardinality consumer must use the identical effective
  record set; `unexpected_commands=[]` plus one proven 267 is not an Agent
  command violation.

### Scheduled Task `Ready` is not campaign completion

- Symptom: Task Scheduler reports `Ready` while token-owned Codex/Python
  descendants or an unsealed attempt remain.
- Cause: the action shell exited before all descendants and evidence writers.
- Prevention: after `Ready`, use a fresh generic process query whose own path
  omits the campaign token. Require zero matching descendants plus the sealed
  summary and attempt manifest before unregistering the task.

### Topic stream output is NDJSON, not one Gateway JSON document

- Evidence: #91 macOS root `imac-topic-3b26237-r2-typ24-stream` completed one
  30-second `stream-topic` lifecycle, received the exact Mac and Windows
  SoundBank events, emitted a successful `duration_elapsed` terminal record,
  and unsubscribed cleanly. The Broker and real publisher path passed, but the
  shared command classifier omitted `stream-topic` and treated the successful
  command as non-Gateway/unexpected.
- Cause: the classifier knew the single-document `wait-topic` route but neither
  the `stream-topic` subcommand nor its started/event/terminal NDJSON framing.
  A separate earlier frozen root also showed that result-only `platform` and
  `language` Topic disclosures must be sealed even when they are deliberately
  absent from the subscription match.
- Prevention: keep `stream-topic` in the one shared Gateway subcommand registry;
  classify success from its final terminal NDJSON record, while the Broker
  independently validates the complete ordered record lifecycle, event count,
  and unsubscribe result. Seal only the exact event-result scopes required by
  the oracle in addition to match scopes. Never parse the whole stream with one
  `json.loads`, and never repair these harness omissions by weakening the
  production Topic contract.
- Follow-up: root `imac-topic-9759832-r3-typ24-stream` passed every Agent,
  Broker, NDJSON, publisher, event, artifact, and final-response gate, then the
  final dispatch audit failed because it still required one dispatcher `call`
  row. That invariant belongs to `wait-topic`; `stream-topic` opens a
  `SubscriptionManager` lifecycle and therefore proves zero dispatcher-call
  rows plus the sealed ACK, ordered NDJSON events, successful terminal, and
  explicit unsubscribe cleanup. Every archive validator must branch on the
  sealed lifecycle instead of treating all Topic evidence as a wait result.

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
- Pre-root addendum: the first `f8968f7` runtime-control launcher returned task
  result 1 before Python because PowerShell opened stdout redirection inside the
  ignored `skills/waapi-skill-workspace` directory before that directory
  existed. It created no campaign root, Codex process, or semantic evidence.
  Create the workspace/log parent before the redirected native command and put
  wrapper-preflight errors in an already-existing directory.

- Re-observed: the final #89 Windows root `iwin-cli-console-c216f68-r1`
  exported `InteractiveToken` but omitted the default `RunLevel` element. The
  registered Principal reported `Limited`; that two-source attestation allowed
  the campaign to run in desktop session 1, pass 1/1 plus verify-only, and
  remove the task with zero scoped residual processes.

### macOS foreground ownership and TCC

- Symptom: a unified shell receives `SIGTERM`, a `nohup` child outlives its
  attempt, or a background shell under `Documents` triggers TCC.
- Cause: the formal campaign lacks a one-shot user LaunchAgent, or its program
  routes through a protected temporary shell script.
- Prevention: put the exact Skill-local Python and campaign argv directly in a
  `RunAtLoad=true`, `KeepAlive=false` LaunchAgent. Prove one run, sealed output,
  and zero scoped processes, then boot it out.

### Authoring old-cache modal is not a project-version mismatch

- Evidence: isolated Wwise 2022.1 Authoring copies used for #87 displayed the
  exact modal `The project cache has been deleted because it was generated with
  an older version of Wwise.` After one acknowledged `OK`, `getInfo` reported
  v2022.1.19 build 8584, `isCommandLine=false`, and `getProjectInfo.path`
  matched the exact copied sandbox; the transport and Remote lifecycle tests
  then passed.
- Cause: the copied/prelaunch-normalized project references a disposable cache
  whose version marker is older than the running Authoring build. Wwise deletes
  and rebuilds that cache; it is not refusing or converting the authored
  project.
- Prevention: inspect the full modal text before interacting. Acknowledge only
  this exact known cache message, once, then require matching `getInfo` version,
  exact sandbox project path, and non-command-line host readiness. Any different
  conversion, migration, save, plug-in, or license dialog remains blocked for
  explicit diagnosis.

### macOS document-open hands `.wproj` to the wrong Wine boundary

- Evidence: the #88 macOS Authoring preflight launched Wwise 2025.1 with
  `open -a Wwise <sandbox>/SampleProject.wproj`. The Wine wrapper displayed
  “There is no Windows program configured to open this type of file” (and its
  localized equivalent), while WAAPI later listened with
  `ak.wwise.no_project_loaded`. The disposable copy was unchanged and no test
  command ran.
- Cause: macOS document association forwards the host path to the Wine wrapper;
  it is not the Wwise Project Launcher's Windows-path-aware project-open flow.
- Follow-up evidence: this wrapper's `wwise_launcher` discards application
  arguments, so `open --args` cannot repair the handoff. Its Wine bottle maps
  the user home to `Y:` and the filesystem root to `Z:`, and `winepath -w`
  correctly converted the sandbox path. Directly invoking the packaged Wine
  runner with `Wwise.exe Y:\\...\\SampleProject.wproj` avoided the association
  error and started the intended executable, but the 2025.1 instance still
  reported `getInfo.isCommandLine=false` plus
  `ak.wwise.no_project_loaded`. Treat that as executable-start evidence, not
  project-open evidence.
- Confirmed route: invoke the packaged Wine runner with both explicit Windows
  arguments: `start.exe /wait <Wwise.exe> <Y:\\...\\SampleProject.wproj>`.
  Passing only the document to `start.exe` can fall back to the Project
  Launcher and lose the project argument. The explicit executable-plus-project
  form loaded the isolated #88 sandbox on both 2022.1 and 2025.1, reached the
  expected `Project Load Log`, and returned
  `getInfo.isCommandLine=false` plus the exact sandbox Windows path from
  `getProjectInfo.path`. Do not substitute `open -a`, `open --args`, a bare
  project document, or a Wwise.exe process with no matching project argv merely
  because a window appeared.

### Console project transitions cross the same Wine path boundary twice

- Evidence: #89 macOS `ak.wwise.console.project.open` first rejected the exact
  existing sandbox POSIX path as nonexistent. After transient dispatch gained
  audited Y:/Z: translation, execution succeeded but verification still
  compared the stored POSIX path with Wwise's equivalent `Y:\...` readback and
  reported `PROJECT_TRANSITION_MISMATCH`. The Project object also exposed the
  hierarchy `path` as `\` and the filesystem identity in `filePath`.
- Cause: Console project create/open had been omitted from the closed Wine
  path-adaptation set, absolute project-path selection accepted a non-filesystem
  hierarchy path first, and the transition verifier canonicalized host and Wine
  syntax without first proving that they named the same local file.
- Prevention: include only the reviewed Console create/open URIs in transient
  path adaptation, select the first strict absolute `path`/`projectPath`/
  `filePath`, and during local-Wine verification round-trip the live Y:/Z: path
  to one existing regular non-symlink `.wproj` before comparing host identity.
  Native Windows remains identity mode; remote or unsupported drives are never
  localized. Final candidate `41d07ab` passed all four #89 Wwise 2025.1 shapes
  on both hosts plus 2022.1 SoundBank generation on both hosts.
- Modal handling: first require WAAPI to report the exclusive-lock reasons
  `Loading project in progress` and `Waiting for user to close a modal dialog`.
  Then enumerate the same Wine desktop's top-level windows and click only when
  exactly one title is `Project Load Log` and exactly one child control has
  class `Button` and text `Accept`. The #88 runner compiled this bounded helper
  with the Wwise bottle's packaged Wine Mono `csc.exe`; it accepted the modal
  on both 2022.1 and 2025.1. A missing, duplicate, renamed, localized, or
  different button is `BLOCKED`, not permission to send blind Enter/Alt keys.
  After the click, repeat the exact version, Authoring-host, and sandbox-path
  checks before any test dispatch.
- Prevention: derive the Windows path with the same bottle's `winepath -w`,
  open it through that bottle's `start.exe`, and handle only the exact expected
  sandbox warning. Project Launcher **Open Other/Browse** remains the manual
  fallback. Continue only after
  `getInfo.isCommandLine=false` and `getProjectInfo.path` resolves to that exact
  sandbox copy. A listening 8080 socket proves Authoring readiness only; it
  does not prove that a project is loaded. Close the association error and
  restart the launch flow instead of retrying `open -a ... <wproj>` or claiming
  success from a Windows-shaped path or visible window alone.
- GUI-control pitfall: Computer Use `get_app_state` transparently launches a
  missing macOS app. A Wwise.exe started directly through Wine can be healthy
  without macOS registering the enclosing `.app` as running, so even a prior
  Wwise.exe process/argv check does not make this probe safe. Do not target the
  `.app` with `get_app_state` during a direct-Wine launch. The probe can create
  a second no-project launcher over the intended sandbox instance; close only
  that launcher's wrapper process group and preserve the Wwise.exe whose argv
  contains the sandbox path. Use exact process/WAAPI evidence for liveness and
  an already registered interactive launch path when modal inspection is
  required.

### macOS offline Fresh replay inherited an unrelated Authoring launch

- Evidence: the #88 `soundengine_business_1` campaign sealed
  `offline_only=true`, `live_config.used=false`, and `wwise_started=false` for
  its fresh PASS. Before its identical verify-only replay, an operator-side
  phase transition nevertheless opened Wwise Launcher and three generations
  of idle `Wwise2019x64` bottle helpers outside the campaign. No project
  `Wwise.exe` or WAAPI listener existed, and the campaign evidence confirmed
  that the harness had not requested Wwise.
- Cause: the preceding real-Authoring validation procedure was carried into a
  later offline-only step. This was orchestration outside the sealed campaign,
  not loss of `--offline-only` inside the runner.
- Prevention: on macOS, treat `offline_only=true` as a zero-Wwise phase
  boundary because Authoring, Console, and their helpers share the Audiokinetic
  CrossOver bottle. Before a fresh run or verify-only replay, require zero
  Wwise project/Console processes and zero listeners on the selected WAAPI
  ports, then invoke only the exact campaign command. Inspect liveness from
  sealed campaign evidence; GUI app-state probes and Authoring launch helpers
  are not part of this lane. If an unrelated Wwise/Launcher instance appears
  before the campaign starts, stop, prove that no project process owns the
  shared bottle, clean only those idle test helpers, re-establish the zero-Wwise
  preflight, and then continue. Native Windows has no shared-bottle constraint;
  use the scoped rule below instead.

### Codex prompt inventory shortened Skill locators behind root aliases

- Evidence: exact #88 macOS root `imac-soundengine4-92fb617-r1` stopped before
  the first Agent command with 0 PASS / 1 infrastructure BLOCKED / 3 pending.
  `codex debug prompt-input` listed five bundled system Skills as `r0/...` and
  the task-local `waapi-skill` as `r1/...`; the old audit treated every short
  locator as a non-system, non-target path. The root sealed one attempt
  manifest, started no Wwise, issued no Broker/Gateway command, and was not
  resumed or replayed.
- Cause: newer prompt serialization may disclose one `Skill roots` table and
  use its `rN` aliases in the following Skill inventory. The isolation audit
  understood only full host paths even though the prompt still contained the
  exact path mapping.
- Prevention: parse root mappings only from system/developer instruction
  content, accept an alias only when it maps to exactly one root, and expand
  only traversal-free relative Skill locators. After expansion, retain the
  existing hard gates: bundled Skills must resolve below the exact disposable
  Codex `.system` root, the target must resolve to the one task-local detached
  `waapi-skill`, and personal `.agents/skills`, unknown aliases, ambiguous root
  definitions, duplicates, or mismatched targets remain rejected. Freeze the
  pre-Agent root and use a new candidate/root after this audit contract changes.

### Explicit transaction state was dropped from copy-exact continuations

- Evidence: the #88 macOS Authoring project-open Preview used an explicit
  external `--state-dir`, but its returned `next_command.shell_command` omitted
  that global argument. Executing the selected field verbatim failed with
  `TransactionNotFound`; no project-open dispatch reached Wwise.
- Cause: `transaction_next_command` encoded only the subcommand argv and
  assumed that the next shell inherited the same ambient state configuration.
  A CLI-selected state root is process-local and cannot be recovered from that
  assumption.
- Prevention: every copy-exact continuation generated from an invocation with
  explicit `--state-dir` carries that same resolved absolute argument before
  the subcommand in `full_argv`, POSIX `shell_command`, and both native-Windows
  envelopes. Keep `gateway_argv` as the subcommand projection, execute only the
  selected encoded field, and test paths containing spaces plus both Windows
  decoders. Never reconstruct the missing global argument by hand.

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
- Prevention: for ordinary pytest only, set `WAAPI_TEST_PYTHON` to one exact
  pre-provisioned developer interpreter from the locked Poetry environment,
  then run `ci\test.bat` directly through SSH. `ci/test_driver.py` verifies
  Python 3.11-3.13 plus the exact `pytest` and `waapi-client` versions before a
  test-context header or Wwise startup; an incomplete selection exits 4 with
  `TEST_ENVIRONMENT_BLOCKED`. Provision a new worktree-local Poetry environment
  only when no complete interpreter exists. This is not a Fresh campaign and
  does not use Task Scheduler. Launcher failures receive no test result or
  retry number. From Git Bash, invoke the batch file through
  `cmd.exe //d //s //c`; `/c` may be path-converted into an interactive prompt
  and must not receive test credit.

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
- Second follow-up: roots `imac-pset-3531da5-r3` and
  `iwin-pset-3531da5-r3` completed the typed-name binding, but the Broker still
  expected the internal generic `--role/--value` declaration while both Agents
  naturally emitted dedicated flags from the disclosed business field names.
  Do not teach Agents internal field envelopes. Project-setting declarations
  expose dedicated business flags and a complete `append` shape, and the sealed
  protocol must use that same public continuation.

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

### Optional-plugin isolation is version-layout-specific

- Evidence: the #87 macOS Authoring preflight for Wwise 2025.1 stopped before
  Wwise launch because the current broad optional-plugin isolator requires the
  2022 SampleProject `Master-Mixer Hierarchy` layout. The copied 2025.1 project
  has no such directory, so `normalize_project_copy` raised
  `ProjectPrelaunchError` after creating only the disposable copy and I/O root.
  The source project remained untouched and the preflight receives no real-host
  credit.
- Prevention: do not treat `isolate_optional_sample_plugins=true` as a
  cross-version generic switch. Use it only for a pinned fixture layout that
  its preconditions accept, or implement and deterministically test a separate
  version-specific isolator before launching Authoring. Never bypass the
  required isolation because a newer SampleProject moved or renamed its work
  units; freeze the failed preflight and select a supported matching version.

### A generated SoundBank file does not override WwiseConsole failure

- Evidence: #89 direct Wwise 2022.1 diagnosis wrote `Init.bnk` and the related
  metadata files, but still exited 1 because the copied SampleProject's Init
  Bank referenced the unavailable ReWwire Sender and Auro Headphone effects.
  `--continue-on-error` preserved the files but did not change the failed exit.
- Cause: WwiseConsole always generates Init alongside the requested Banks. A
  file-only oracle can therefore observe a usable artifact from a command that
  Wwise truthfully classified as partially failed.
- Prevention: keep the nonzero exit fail-closed and never promote it to PASS
  merely because `.bnk` files exist. For the pinned 2022 SampleProject, run the
  existing identity-checked optional-plugin isolator on the disposable project
  copy before Wwise starts; keep the immutable source untouched. Use the
  separate reviewed 2025 Auro profile for that fixture layout.

### Python 3.11 `wave` does not parse Wwise extensible PCM

- Evidence: the first #90 real Wwise 2025.1 Tone tracer bullet successfully
  dispatched `ak.wwise.debug.generateToneWAV` and wrote a nonempty WAV, but the
  test oracle raised `wave.Error: unknown format: 65534` before checking its
  audio format. Wwise had emitted standard `WAVE_FORMAT_EXTENSIBLE` PCM rather
  than classic format tag `1`.
- Cause: Python 3.11's standard `wave` reader does not support extensible PCM.
  Treating that parser failure as a product failure would discard valid Wwise
  output; treating file existence alone as PASS would lose the business
  oracle.
- Prevention: inspect the RIFF `fmt ` and `data` chunks independently. Accept
  classic PCM or extensible PCM only when the sub-format GUID is PCM, then
  verify channel count, container bit depth, sample rate, block alignment, and
  frame count. Wwise may write extensible `wValidBitsPerSample` as either zero
  or the container bit depth. Do not weaken the check to file size or upgrade
  the repository interpreter merely to make this artifact readable.

### Independent CLI declaration groups are not a semantic sequence

- Evidence: #89 macOS Fresh root `imac-cli-console-03ebea9-r1` selected the
  exact SoundBank-build API and supplied every reviewed business value, but put
  the platform output mapping before the source-control policy. The Broker
  expected the reverse textual order and rejected the declaration before the
  Gateway or Wwise; the root remains a frozen semantic FAIL without replay.
- Cause: the formal protocol treated independently named `--value`, `--item`,
  `--mapping`, and `--toggle` groups as an ordered workflow even though the
  production parser builds one closed field map and rejects duplicate fields.
- Prevention: canonicalize only complete, uniquely keyed CLI/Console groups to
  the reviewed order before exact Broker comparison. Preserve collection item
  and mapping contents in their identity keys, and keep every supplied value,
  duplicate, omission, extra field, and revision binding exact. Do not repair
  this transport-only difference by adding prompt wording or by weakening the
  final materialized request comparison.

### SoundBank build intent must identify its execution channel

- Evidence: #89 native-Windows root `iwin-cli-console-dcd0bd0-r1` received a
  generic “generate SoundBanks” request, selected the already valid named
  `soundbank.generate` operation from `operations`, and was rejected because
  this targeted profile expected the distinct WwiseConsole CLI route. The root
  remains a frozen semantic FAIL; no Preview, execute, or Wwise process ran.
- Cause: both the connected Core SoundBank API and WwiseConsole command-line
  API satisfy generic build wording. The test prompt omitted the user-visible
  execution-channel choice, so treating either route as the only semantic
  answer would grade an ambiguity rather than Agent capability.
- Prevention: a Fresh routing case for the CLI/Console family must say
  `WwiseConsole 命令行` (or an equivalent explicit channel) while still hiding
  URIs, Gateway commands, Draft mechanics, and native options. Final candidate
  `c216f68` passed 1/1 fresh plus identical verify-only on both hosts; the
  Windows run used an attested `InteractiveToken` / `Limited` task and removed
  it after zero scoped residual processes. Predecessor `d6d6709` also passed
  this case, but later packaged changes prevent treating it as final-candidate
  evidence.

### A dynamic Business request is replayed from its durable Draft

- Evidence: #88 macOS root `imac-soundengine4-68411e0-r2` and native-Windows
  root `iwin-soundengine4-92fb617-r1` both produced the correct
  `registerGameObj` Preview, including a Gateway-generated native game-object
  ID, but the Broker changed the successful runner result to FAIL. It tried to
  reconstruct the request with the removed shallow Operation Composer and
  reported that no shallow Adapter existed.
- Cause: the semantic protocol intentionally omitted a static request witness
  because the native ID is derived from the live Draft authority. The Broker
  treated that absence as proof of a legacy Composer flow even though the
  durable Draft contained a complete `business_session`.
- Prevention: when a production Draft contains a durable Business session,
  replay it through the exact Business Adapter selected by `draft-start` and
  compare the Agent's Preview with that materialized request. Use the shallow
  Composer replay only for Drafts that truly have no Business session. A
  model-authored placeholder for a Gateway-owned dynamic ID is not an
  acceptable witness or workaround.

### Final prose is not an exact-term oracle

- Evidence: #88 macOS root `imac-soundengine4-425793e-r5` completed the exact
  Broker protocol and closed Preview for all four selected units. Monitor and
  Game Object were nevertheless recorded as FAIL only because the final prose
  said `Profiler Capture Log` instead of `监控`, and `运行时对象` instead of
  `游戏对象`. Both replies explicitly said a Preview was generated and nothing
  was executed; every structural, integrity, no-execute, and closed-request
  gate passed. The sealed root remains unchanged, while manual review and the
  user's explicit acceptance classify those two outcomes as semantic passes.
- Cause: `preview_reported` duplicated business validation with exact noun
  markers even though the canonical request and Broker evidence already owned
  the target, values, route, and execution status.
- Prevention: use structured request, real-Wwise/readback, Broker, and
  execution-state gates for business truth. Final prose need only make the
  Preview status clear; ordinary synonyms, translations, word order, and
  omitted implementation nouns do not fail a run. Keep grossly contradictory
  claims visible for review, but never require a model to repeat fixed wording.

### An unrelated Windows Console is not an offline Fresh conflict

- Evidence: the #88 native-Windows Monitor verify-only controller stopped
  before task creation when it saw the user's independent ReWwire
  `WwiseConsole.exe waapi-server` process. That Console listened on port 18090;
  neither 8080 nor 8090 was occupied, and the sealed Fresh campaign was
  `offline_only=true`, `live_config.used=false`, and `wwise_started=false`.
  After the controller was scoped correctly, the identical verify-only audit
  passed with task and campaign exit 0 while the same Console remained PID
  12464 on port 18090 before and after; no task or campaign descendant remained.
- Cause: an operator-side controller treated the machine-wide count of
  `Wwise.exe` and `WwiseConsole.exe` as an exclusivity lock. Windows supports
  concurrent Console processes, and a verify-only replay starts neither Codex
  nor Wwise.
- Prevention: for native-Windows offline Fresh and verify-only work, attest the
  sealed offline campaign contract and check only the scheduled task plus
  campaign-owned descendants. Existing unrelated Console processes and their
  distinct listeners are observations, not blockers. For a live campaign,
  reserve and verify its exact port, sandbox, project, and owned lifecycle;
  never require every Wwise process on the host to be absent.

### Long Windows task controllers do not belong in `-EncodedCommand`

- Evidence: the first two #91 final-candidate TYP24 launch attempts encoded the
  complete registration controller as UTF-16LE Base64. PowerShell reported
  that `-EncodedCommand` was not properly encoded, even though the same local
  encoder works for short status probes. Neither attempt created a Scheduled
  Task, temporary root, or campaign root. Transferring the same controller and
  action wrapper as temporary UTF-8 `.ps1` files immediately registered the
  attested `InteractiveToken` / `Limited` task; both final Windows Fresh roots
  and both verify-only audits then passed.
- Cause: Windows OpenSSH reconstructs a native remote command line. A large
  Base64 controller can cross or approach one of the intervening command-line
  length/serialization limits and arrive truncated, so PowerShell rejects the
  envelope before parsing the script. The error does not prove that the
  campaign, standalone Codex, Broker, or Task Scheduler is broken.
- Prevention: reserve `-EncodedCommand` for small read-only probes and polling.
  For a formal campaign, transfer a temporary profile-free controller and
  action wrapper over SSH, invoke only the controller with `pwsh -File`, and
  keep the actual campaign inside the registered interactive task. Attest the
  exported `InteractiveToken` and registered `Limited` principal, record exit
  code and logs, remove the task and temporary scripts, preserve the campaign
  evidence, and never retry a failed semantic root.

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
