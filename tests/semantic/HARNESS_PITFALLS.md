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

### Attest the exact current standalone Codex release

- Evidence: Windows Fresh roots using standalone Codex 0.146 could enter the
  correct `InteractiveToken` / `Limited` task and then stall for about 203
  seconds on the first exact PowerShell `Get-Content` Skill read. The same
  query lane passed fresh plus verify-only after switching to the official
  user-owned 0.151 executable.
- Installer pitfall: an installer started through SSH may inherit Git's `tar`
  and fail while unpacking an otherwise valid release. Run the ARM64 installer
  through PowerShell with a sanitized System32/PowerShell `PATH`, then attest
  the exact release path, executable SHA-256, and direct `--version` result.
  A visible shortcut, package directory, or PATH hit is not executable proof.
- Prevention: freeze a pre-command stall as infrastructure evidence; do not
  increase timeouts or retry its root. Upgrade or repair the standalone CLI,
  create a new root, and keep the Scheduled Task desktop contract unchanged.

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

### A terminal sentinel does not prove an unabridged Windows Skill read

- Evidence: #60 Windows root `iwin-issue60-315fe8f-r20-remaining20` read
  `waapi-operate.md` with the exact profile-free PowerShell Core command and
  returned exit 0 plus the terminal sentinel, but the archived output was 254
  characters shorter than the sealed source. Exact read classification
  therefore rejected it. The Agent still continued, so the affected unit was
  correctly frozen without PASS credit.
- Cause: the Codex shell-output projection can elide content while retaining
  the tail; checking only the sentinel misses that middle omission.
- Prevention: exact source/output byte-normalized equality remains the credit
  gate. Later r23 evidence showed clipping can begin well below that earlier
  26,500-byte estimate, so keep every CRLF-expanded lane reference at or below
  20,000 bytes. A Program regression enforces that ceiling. Never weaken the
  equality gate or replay a clipped root.

### Repeated Windows path separators are not an extra Skill read

- Evidence: #60 r26 completed the exact PowerShell Core `Get-Content` reads,
  returned byte-identical Skill/reference content, and completed the intended
  Gateway workflows, but Codex wrote doubled `\\` separators inside the
  single-quoted task-local relative locator. PowerShell and the Windows
  filesystem resolved the same fixed files; the harness alone classified the
  successful read as an unexpected command.
- Prevention: for the sealed Windows task-local Skill locators only, collapse
  one or more backslashes before matching the fixed allow-list. Continue to
  reject forward slashes, absolute/drive paths, empty components, and `..`, and
  retain the exact profile-free PowerShell Core wrapper, complete-byte output,
  read order, and one-read cardinality checks. This equivalence does not apply
  to Gateway argv, user paths, or shell commands generally.

### macOS foreground ownership and TCC

- Symptom: a unified shell receives `SIGTERM`, a `nohup` child outlives its
  attempt, or a background shell under `Documents` triggers TCC.
- Cause: the formal campaign lacks a one-shot user LaunchAgent, or its program
  routes through a protected temporary shell script.
- Prevention: put the exact Skill-local Python and campaign argv directly in a
  `RunAtLoad=true`, `KeepAlive=false` LaunchAgent. Prove one run, sealed output,
  and zero scoped processes, then boot it out.
- Addendum: a LaunchAgent that executes a wrapper script stored under
  `Documents` can fail with macOS `Operation not permitted` before campaign-root
  creation. Put the Skill-local Python plus exact campaign arguments directly
  in `ProgramArguments`; do not move the wrapper elsewhere and treat that as a
  semantic retry.

### A macOS verify-only replay can discover a different Codex binary

- Symptom: a passing LaunchAgent root immediately rejects a foreground
  `--resume --verify-only` invocation because the immutable campaign config no
  longer matches, even though verify-only would start neither Codex nor Wwise.
- Cause: the LaunchAgent default `PATH` can select the Codex binary packaged in
  the desktop app while an interactive shell selects a Homebrew Codex binary.
  The formal config fingerprints the exact executable, version, and digest for
  replay even when that replay will not execute it.
- Prevention: read the sealed campaign config or pin `--codex-binary` on the
  initial LaunchAgent. Pass that exact absolute binary path on verify-only as
  well; never relax the immutable comparison or treat two Codex installations
  as equivalent.

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

### Natural operation selection may begin with `operations`

- Evidence: one #60 full root correctly used the compact `operations` catalog
  before several named `operation-schema` calls, but the formal Broker required
  the named schema as command one and rejected every such task before Gateway
  dispatch.
- Cause: the test protocol treated its runner-owned exact operation identity as
  if it were already known to the fresh Agent. The Skill allows direct schema
  lookup only when the exact name is visible; natural-language business intent
  may first require one catalog read.
- Prevention: typed-profile protocols whose first public step is a named
  `operation-schema` accept exactly one initial `operations` step. Preserve the
  rest of the ordered protocol, terminal counts, and immutable operation name;
  repeated or late discovery remains rejected.

### Mixed-type query rows may omit inapplicable optional accessors

- Evidence: a #60 descendants query requested source language across a result
  containing both containers and `AudioFileSource` objects. Wwise omitted the
  source-language accessor on containers, and Gateway incorrectly returned
  `INVALID_QUERY_RESULT` even though identity fields and applicable source rows
  were valid.
- Cause: business projection treated every requested optional property or
  reference as mandatory on every heterogeneous row.
- Prevention: keep `id`, `name`, `type`, and `path` strict, but project a
  requested property/reference/derived business field as JSON `null` when it
  is not applicable to that row. Missing required identity still fails closed;
  this is not permission to accept malformed result rows.

### Do not kill unrelated Wwise, Console, REAPER, or Codex work

- Evidence: the Windows desktop may concurrently run the user's separate
  ReWwire/Wwise Console development workflow. Its processes can share product
  names and WAAPI-related components without belonging to the Fresh campaign.
- Prevention: ownership requires the campaign token, sealed sandbox/project
  path, task identity, or recorded descendant relationship. If an unowned
  process occupies a required port or host prerequisite, postpone that lane or
  report it blocked. Never terminate it from a name-only process match.

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

### A copied Windows live config can still name the old worktree

- Evidence: #91 candidate `8d5499e` passed both native-Windows Topic live
  tests, then all three selected 2022.1 destructive tests stopped before Wwise
  launch because the ignored copied `live-environment.json` still named
  `C:\Git_Repos\waapi-skills\tests\_org\...` instead of the frozen candidate
  worktree. The strict destructive fixture correctly rejected that mismatch.
- Cause: the local config is machine-specific and ignored, but its
  `sample_project` and `sandbox_root` values may be absolute. Copying the file
  into a detached candidate does not rebase those paths.
- Prevention: after creating a Windows candidate worktree, localize each
  selected version's ignored `sample_project` and `sandbox_root` to that exact
  worktree before any strict real test. Attest the printed Test Context. A
  pre-launch path mismatch is zero real attempts; correct only the ignored
  config and continue the unexecuted lane.

### A Scheduled Task log redirection needs its parent, not its campaign root

- Evidence: the first #91 `8d5499e` Windows TYP21 task had the correct
  `InteractiveToken` / `Limited` principal but ended before campaign creation:
  `Out-File` opened the task log below the absent ignored
  `skills\waapi-skill-workspace` directory before the runner could create its
  campaign root.
- Cause: PowerShell opens pipeline redirection before invoking the campaign.
  The campaign root must remain absent for a fresh run, but the separate log's
  parent must already exist.
- Prevention: create only `skills\waapi-skill-workspace` before the task
  action. Keep the exact campaign root absent, place task logs beside it, and
  credit no attempt when neither the root nor Codex/Wwise process was created.

### An incomplete initial Skill read freezes the Windows Fresh root

- Evidence: #91 Windows root `iwin-topic-8d5499e-typ21-r1` ended BLOCKED with
  one `started_without_completed` item for the profile-free PowerShell Core
  `Get-Content -Raw -Encoding UTF8 ...SKILL.md` command. No Gateway or Wwise
  dispatch occurred, cleanup completed, and the root was not replayed.
- Cause: the formal runner cannot prove a completed Codex command lifecycle
  when the standalone task ends while its first Skill read is still marked in
  progress; inferring success from a readable file would corrupt evidence.
- Prevention: preserve the lifecycle failure and freeze the root. Do not
  convert it to a semantic FAIL or retry the root; a later changed candidate
  may use one new campaign root after the exact runner and desktop preflight.

### A production interface migration must migrate the Fresh oracle too

- Evidence: #60 macOS root `imac-issue60-f361093-r1` used the frozen deep
  Skill candidate but retained the older `typed_input_cross_version_25`
  protocol. The Agent correctly used the sole `status` route while the Broker
  expected `status -> request-schema -> typed-zero-call`; it correctly read
  `query-schema` while the Broker expected a retired raw `query-object`; the
  third unit then blocked before Codex because the oracle requested a removed
  generic typed-Draft adapter for `object.create`. The root stopped at 0 PASS /
  2 FAIL / 1 BLOCKED / 22 pending with unchanged source hash and mtime and was
  frozen without replay. The simultaneous Windows root
  `iwin-issue60-f361093-r1` independently froze as infrastructure BLOCKED on
  one incomplete Codex command lifecycle and grants no semantic evidence.
- Cause: Program, Non-live, and real-Wwise gates proved the production deep
  interface, but the representative Fresh profile still materialized its
  expected commands from pre-migration helper recipes. An exact Broker then
  treated correct current commands as unexpected, and a removed Adapter became
  a setup blocker rather than an Agent result.
- Prevention: when a public Gateway seam is removed or deepened, include its
  executable Fresh protocol/oracle in the same deterministic migration gate.
  Build expected steps only from the current business declaration, keep frozen
  historical recipes solely for archive replay, and run a no-Codex
  constructibility regression over every selected profile unit before opening
  a formal root. Never restore the retired production interface to make an old
  oracle pass, and never relabel a protocol-construction BLOCKED result as an
  Agent failure.

### A current Fresh oracle must allow bounded read-only disclosure choices

- Evidence: #60 macOS diagnostic root
  `imac-issue60-9683ec1-r2-priority3` reached all three priority units. The
  `status` unit returned the correct normalized `status.wwise` projection but
  the oracle compared it with the larger raw `getInfo` object. The query unit
  read both `query-schema` and `query-schema --advanced` before issuing the
  exact closed business `query-object`; the Broker rejected the second harmless
  disclosure. The create unit used repeated `--path-segment` flags and default
  identity fields while its collision oracle still expected removed `--path`
  and `--return-field` flags. The root was also invalidated by a harness edit
  during execution and grants no PASS credit. The simultaneous Windows
  diagnostic ended 0 PASS / 1 FAIL / 1 BLOCKED / 1 pending and likewise grants
  no credit.
- Cause: the oracle mixed three native representations with current public
  contracts: raw `getInfo` versus normalized `status`, one exact reasoning
  trace versus several equivalent bounded schema reads, and retired query
  flags versus the business path-segment grammar.
- Prevention: compare each public result with its own documented projection,
  not the native payload behind it. For a closed business query, allow direct
  execution, the ordinary schema read, the advanced read-only schema, or both
  schema reads; authenticate every selected disclosure and still require the
  same final business query. Compile trusted Wwise paths through the shared
  canonical segment helper and rely on default identity fields. Once a Fresh
  root starts, keep every candidate-owned file immutable until all selected
  hosts seal, even when the discovered fix is obvious.

### Live Broker normalization must be replayed by the archive validator

- Evidence: #60 macOS root `imac-issue60-f282029-r3-priority3` produced three
  scenario-level PASS outcomes on the frozen candidate, including a verified
  real `object.create`. The outer archive validator nevertheless classified
  the query and create units BLOCKED. It rebuilt the query from the historical
  raw recipe instead of the typed-profile business recipe, and it compared the
  Agent's valid task-local declaration id `alert` with the protocol placeholder
  `root-01` without running the same Broker binding used during execution.
- Cause: execution and archive replay shared `_validate_step` but not all
  deterministic pre-validation normalization. The archive also omitted the
  profile-specific recipe migration that constructed the sealed plan.
- Prevention: rebuild typed-profile archives through the same reviewed recipe
  selector used before Codex, and apply the Broker's bounded task-local
  declaration-id binding before replay validation. This does not trust the
  archived id: the binding still enforces syntax, uniqueness, position, and
  exact downstream payload/hash checks. A scenario PASS reclassified BLOCKED
  by the outer verifier remains diagnostic only; repair the verifier and use a
  new root rather than editing or replaying the sealed root.

### Broker projection must follow the copy contract, not a sibling array

- Evidence: #60 roots `imac-issue60-aae95e9-r11-fail7` and
  `iwin-issue60-aae95e9-r11-fail6` received valid compact business-Draft
  continuations containing `fixed_argv_prefix_copy` plus its instruction, but
  the Broker still required the removed sibling `fixed_argv_prefix` array and
  rejected the command before Gateway/Wwise dispatch.
- Cause: the model-facing receipt and Broker projector encoded the same argv in
  two independently evolving shapes.
- Prevention: decode the instruction-selected copy string through one host
  function, verify its canonical candidate runner, project only that runner,
  and canonically re-encode it. Retain the legacy array path solely for sealed
  replay. Parameterize POSIX, short Windows model commands, long encoded
  PowerShell commands, and tampered-runner rejection.

### Compact business receipts are complete projections, not full Draft dumps

- Evidence: #60 r12 `draft-discover-fields` returned a valid 21,550-character
  object-set receipt that repeated the business contract and every argv array.
  The Windows Agent stopped because it interpreted the large reply as
  truncated. Other update routes had already switched to compact copy-ready
  continuations, so compactness depended on which Draft action ran.
- Prevention: every business Draft bind, discovery, and adapter-update receipt
  removes repeated contracts and `fixed_argv_prefix` arrays, retains the
  instruction-selected copy string and dynamic candidates, and reports
  `response_integrity.complete=true` with
  `compact_projection_is_not_truncation=true`. Durable Draft state remains the
  lossless source for materialization; tests must inspect that state instead of
  requiring the public continuation to echo it.

### Recompute derived archive facts and honor declared terminal prefixes

- Evidence: #60 r12 completed macOS object-set and Lua lifecycles, but the outer
  verifier reclassified them BLOCKED. One gate required cached derived command
  facts to equal a new reconstruction of the sealed `events.jsonl`; another
  accepted an optional terminal prefix and then incorrectly called it RUNNING
  because it was shorter than the maximum step count.
- Prevention: authenticate and compare the raw archived commands and command
  records, then recompute derived classifications from those sealed records and
  use the recomputation as authoritative. After an accepted terminal prefix has
  passed its sequence checks, require its declared `passed`, `complete`, and
  `COMPLETE` state; do not compare its length with the longest possible path.
  Raw command tampering must still fail closed.

### Formal protocols must preserve closed business values

- Evidence: #60 r12 rejected three otherwise correct high-level declarations:
  import rows explicitly repeated the prompt's `language SFX`; Media Pool used
  fixed result field `Path`, which live dynamic-field discovery did not list;
  and Lua supplied the prompt's complete `wa_args` object instead of manually
  decomposing it into typed leaf flags.
- Prevention: accept exactly one explicit `SFX` language group on a
  `sound-sfx` import row and reject other or duplicate derived language values.
  Treat `Path`, `FileId`, and `Db` as fixed Media result fields while retaining
  the business alias `name/file` for `Filename`. Expose strict
  `--arguments-json` for one complete Lua arguments object, reject duplicate
  keys and non-finite JSON, and keep repeated typed `--argument` only as a
  mutually exclusive compatibility form. The Broker and archive verifier must
  normalize these forms through the same closed contract.

### A complete lane-reference read must fit the Codex shell-output envelope

- Evidence: #60 native-Windows root `iwin-issue60-616fe68-r10-fail9` reached
  the correct Lua Preview with five authenticated Gateway commands, but the
  task gate classified the required `waapi-operate.md` read as unexpected.
  PowerShell returned the beginning and terminal sentinel while the Codex
  shell transcript silently omitted an interior slice: 28,617 visible
  characters versus 30,689 source characters. The root remains frozen FAIL.
- Cause: a terminal sentinel alone cannot prove a whole-file read when the
  host transcript may preserve both ends while clipping the middle. The lane
  reference had grown beyond the observed output envelope.
- Prevention: keep both LF and Windows-rendered `waapi-operate.md` below
  27,000 UTF-8 bytes, with a deterministic size regression and one terminal
  sentinel. Remove repeated
  prose in favor of Gateway schemas/continuations; never weaken byte-for-byte
  read validation or grant PASS merely because the sentinel survived.

The entry needs a stricter envelope. In #60 native-Windows root
`iwin-issue60-aae95e9-r11-fail6`, exact profile-free PowerShell reads of the
30,445-character `SKILL.md` preserved its beginning and end but exposed only
29,440 characters in one task and 26,902 in another. Root
`iwin-issue60-99dc470-r13-fail5` then lost a 759-byte interior slice from a
26,699-byte LF source while still showing the final paragraph. After the CP936
transport fix, exact candidate `fae4551` r39 still lost one 250-character
interior slice from a 23,713-byte `SKILL.md` while preserving both ends and
adding only its normal terminal newline. This proves the earlier 24,000-byte
entry bound was insufficient. Keep both LF and projected CRLF rendering below
20,000 bytes, enforce both in Program tests, and move conditional detail behind
Gateway schemas or lane references. Never infer completeness from exit code or
visible front/back fragments. Separately, r13 root
`iwin-issue60-99dc470-r13-fail6` had an audio-import Agent skip `SKILL.md` and
read only `waapi-operate.md`; that ordinary semantic failure is not clipping.

### Stable dependency order must preserve independent business row order

- Evidence: r13 Windows audio import submitted Rifle and Shotgun rows in the
  exact manifest order, but the resulting Preview request alphabetized sibling
  effect ids, so the sealed business witness rejected it. The Agent's complete
  batch was otherwise accepted.
- Prevention: use a stable topological order. Dependencies still precede their
  consumers, while dependency-free siblings retain the Gateway's declaration
  order. Test a deliberately non-alphabetic batch through the public business
  planner; import row order is semantic, not transport noise.

### Normalize reflected result shapes from real evidence, not fake fixtures

- Evidence: r13 Windows Media Pool returned `Db` exactly as Wwise 2025.1
  reflects it: `{id, name}`. The production normalizer and old fake fixtures
  expected a string and rejected three valid live rows as
  `MEDIA_BUILD_RESULT_INVALID`.
- Prevention: read the versioned reflected definition and frozen dispatch
  evidence before changing a result normalizer. Validate the exact database
  object and project it as stable `database_id` plus `database_name`; keep fake
  Gateway fixtures faithful to the native result.

### Compare verified mutations with their live-bound reviewed request

- Evidence: r13 Windows audio conversion executed successfully, produced the
  expected cache artifacts, and passed reflected result-schema verification.
  The business Oracle still failed because its static request named object
  paths while the Gateway's reviewed transaction correctly sealed the live
  GUIDs bound from those paths.
- Prevention: derive one exact path-to-GUID mapping from the sealed pre-state,
  require one stable identity per requested object, and compare the terminal
  `agent_result.request` with that live-bound reviewed request. Do not weaken
  the comparison to unordered or partial fields.

### Fresh protocols must accept dependency-ready business interleaving

- Evidence: r13 Windows object-set bound Day and its Bus, discovered Day's
  Pitch field, then declared the now-complete Day row before binding Night and
  Storm. The Broker rejected the declaration only because its static recipe
  placed every binding before every declaration.
- Prevention: allow a unique later business declaration to move forward only
  when all of its response-bound handles already exist. Rebase its revision,
  validate its bounded unique task-local id and exact argv, then reorder the
  sealed step. Missing dependencies, duplicate matches, changed values, and
  import row reordering remain rejected.

### Recompute Windows archive facts from the same sealed command records

- Evidence: r13 root `iwin-issue60-99dc470-r13-fail6` Lua completed all nine
  authenticated steps and its inner task result passed, including exact Skill
  reads and the new `--arguments-json '{"count":3}'` declaration. The outer
  campaign nevertheless marked it BLOCKED because cached
  `no_unexpected_commands=true` differed from one archive recomputation.
- Diagnostic boundary: rebuilding both turns directly from the exact sealed
  `CodexCommandRecord` rows classified every Gateway command and produced zero
  unexpected commands. Preserve this root as BLOCKED; do not replay it or grant
  PASS. Keep raw records authoritative, add the exact Windows JSON command to
  archive regressions, and include the recomputed unexpected command identities
  in any future mismatch instead of reporting only a Boolean gate.

### A bounded business route must also be a classified Gateway subcommand

- Evidence: #60 macOS r15 and native-Windows r14 both executed the complete
  Media Pool `core-call` successfully, returned the exact two sorted rows, and
  passed Broker reconciliation. The task gate still failed
  `gateway_count_exact` / `no_unexpected_commands` because the shared command
  classifier omitted `core-call` from its Gateway subcommand registry.
- Prevention: every public command accepted by a formal protocol must use the
  one shared classifier registry. Add a completed-payload classifier regression
  when a route is added; a correct Wwise result cannot compensate for an
  unclassified command, and the fix must not weaken unexpected-command checks.

### Core business declaration groups are commutative transport facts

- Evidence: #60 macOS r15 audio conversion supplied the exact `io_root`, four
  bound audio-object handles, three platforms, and one language, but placed the
  scalar `--value` before repeated `--role` / `--item` groups. The Broker
  rejected the declaration before Gateway dispatch solely because the sealed
  recipe listed the same groups in another order. Native Windows r14 used the
  recipe order and passed the complete real workflow.
- Prevention: normalize independent `draft-declare-core-plan` groups by their
  closed flag, field, and exact value before comparison. Preserve repeated
  values, reject duplicates or changed values, and keep the original argv for
  execution after semantic equality is proved.

### Windows compact Draft commands need the fixed task-local runner

- Evidence: #60 native-Windows r14 object-set accepted eleven exact business
  commands, then the Agent shortened the very long scenario-root runner path
  while declaring Night. The Broker correctly rejected the altered path; no
  further Gateway or Wwise dispatch occurred.
- Prevention: after verifying the candidate's canonical full runner, project
  compact Windows `fixed_argv_prefix_copy` commands to the fixed literal
  `.agents\\skills\\waapi-skill\\scripts\\run.py`. Keep full candidate paths in
  sealed audit state, accept no other relative spelling, and cover both the
  short model grammar and long encoded-PowerShell fallback.

### Import acceptance prompts must not contradict their parent fixtures

- Evidence: #60 macOS r15 told the Agent both to fill missing hierarchy and to
  add no container rows. The fixture already contained the Rifle and Shotgun
  Random Containers. The Agent therefore bound `Weapons` as an ancestor for a
  new Shotgun row; the Broker rejected it because the direct Shotgun parent was
  required. Native Windows r14 selected that direct parent and passed.
- Prevention: state fixture-owned parents explicitly and ask only for missing
  Sound rows. The Gateway continuation also requires every segment through the
  immediate parent and treats a missing direct parent as a structured stop;
  never silently substitute an ancestor.

### Windows can clip a lane reference even when both ends survive

- Evidence: #60 native-Windows r23 returned the beginning, final sentinel, and
  exit 0 for exact PowerShell reads, yet `waapi-query.md` exposed only 28,810
  characters from a 30,599-byte CRLF source and `waapi-operate.md` exposed
  25,886 characters from a 26,395-byte CRLF source. Query, Topic, and audio
  conversion units consequently failed `skill_reads_exact` without receiving
  semantic credit.
- Prevention: keep both query and operate references below 20,000 UTF-8 bytes
  after CRLF projection and enforce that bound in Program tests. Retain exact
  normalized equality as the credit gate; a sentinel, exit code, or intact
  beginning and end does not prove an unabridged read.

### Windows Console code page can corrupt a complete Skill read

- Evidence: #60 exact candidate `a348da2` returned byte-identical Skill reads
  in native-Windows r37, but r38 archived the same successful profile-free
  `Get-Content -Raw -Encoding UTF8` commands with 89 replacement characters.
  Both affected Agents still built the exact requested SoundBank Previews.
  The failing `SKILL.md` projection was 45 characters longer than the sealed
  source, with 22 mojibake replacement regions rather than an omitted slice.
  An `InteractiveToken` / `Limited` desktop probe then reported Console input
  and output code page 936 while PowerShell's `$OutputEncoding` was UTF-8.
- Cause: `-Encoding UTF8` controls how PowerShell reads the file; it does not
  set the attached Console transport used by every child process. Depending on
  whether Codex received a pipe or Console path, the same Unicode text could be
  emitted through CP936 and decoded as UTF-8.
- Prevention: before PowerShell attestation or any Codex child launch, the
  native Windows harness sets both Console input and output code pages to
  65001 through WinAPI and reads both values back. Failure to set or attest
  them blocks before the Fresh turn. Candidate `fae4551` r39 then produced zero
  replacement characters and passed SoundBank generation, proving the encoding
  repair independently of the remaining clipping boundary. Keep byte-normalized
  source equality as the Skill-read credit gate; accepting mojibake or merely
  setting `$OutputEncoding` does not repair this transport boundary.

### Optional discovery and Composer setup may still complete out of recipe order

- Evidence: #60 macOS r23 metadata completed its selected optional lane, but
  the outer terminal verifier compared the archived consumed order directly to
  the recipe order and reclassified the task BLOCKED. The Broker had already
  accepted a permitted commutative read/setup ordering and sealed every step.
- Prevention: after validating the selected optional lane, run the same
  `gateway_step_sequence_matches` normalization used by the Broker and require
  the sealed commutative groups, exact record set, successful records, and
  terminal COMPLETE state. Do not weaken value or step membership checks.

### Archived conversion identities may change representation without drift

- Evidence: #60 macOS r23 audio conversion sealed object paths in the static
  request, then the live preflight resolved those exact paths to unique GUIDs
  for execution. The archive contained the authenticated GUID request and its
  correct digest, but the outer verifier required literal path equality and
  reported a false BLOCKED result.
- Prevention: accept either the exact static path request or the request formed
  by replacing every sealed path with its unique live-preflight GUID. Bind that
  equivalence only to sealed artifact fingerprints, require complete and
  unambiguous resolution, and continue rejecting any other request or digest.

### Every archive validator must share the same identity equivalence

- Evidence: #60 macOS r24 produced a passing audio-conversion task and passing
  typed archived oracle after replacing sealed object paths with their unique
  live GUIDs. The campaign still classified the unit BLOCKED because its older
  secondary conversion validator independently required literal equality with
  the path request.
- Prevention: when a campaign retains a secondary oracle, make it accept the
  same narrowly proven equivalence as the typed validator. Reconstruct the GUID
  request only from unique `object_path`/`object_id` pairs in the sealed before
  snapshot, compare the complete request, and continue building artifact slots
  from the sealed business paths. Add a full campaign-classification regression;
  a unit-level typed-validator test alone is insufficient.

### Conditional business phases need copy-ready continuations

- Evidence: #60 macOS r24 correctly preflighted the existing `Robot_VO` root
  and bound its direct parent, then skipped `draft-business-configure` because
  `required_next_phase` said to declare the object. The Broker rejected the
  declaration before mutation. The same candidate passed on Windows only
  because that Agent happened to configure merge first.
- Prevention: expose a dedicated `existing_same_name_root_merge` continuation
  whose fixed prefix appends exactly `--name-conflict merge`, mark it required
  before the root declaration, and state that conditional in
  `required_next_phase`. Do not rely on a prose rule beside a contradictory
  generic phase label.

### Windows transaction continuations also need the fixed task-local runner

- Evidence: #60 native-Windows r27 object-set read a correct absolute
  `model_command`, but the Agent changed the long
  `skills\\waapi-skill-workspace` segment into
  `skills\\waapi-skill\\workspace`. The Broker rejected the nonexistent runner
  before `draft-start`; no project change or later Gateway dispatch occurred.
- Prevention: keep the canonical absolute argv in `full_argv` and the encoded
  `shell_command`, but project the selected Windows `model_command` onto the
  one fixed `.agents\\skills\\waapi-skill\\scripts\\run.py` spelling. Resolve
  that spelling only through the sealed task-local Skill installation and
  reject every other relative path. The outer continuation-copy audit must
  compare the selected short runner through that same exact binding while
  still requiring the encoded fallback to decode to absolute `full_argv`;
  native-Windows r28 exposed the otherwise contradictory audit in both Lua and
  object-set before any rejected follow-up reached Gateway or Wwise.

### Editing the candidate worktree invalidates an active Fresh root

- Evidence: #60 macOS root `imac-m60-12caf94-r30-rem22` started from exact
  candidate `12caf94`, then the candidate's packaged Skill source changed while
  later units were still running. A metadata unit consequently reported
  `no_files_changed` even though the Agent had not edited the Skill, and every
  result after the tree drift lost candidate identity. The root was stopped,
  frozen without PASS credit, and its exact campaign, Wwise, and Codex
  descendants were removed.
- Prevention: a Fresh campaign owns an immutable candidate worktree for its
  complete lifetime. Do not patch production, tests, references, generated
  inventories, or other candidate-owned files until every selected host has
  sealed and all token-owned processes have exited. Develop the next repair in
  a separate worktree, or wait; if any candidate file changes during a run,
  freeze that root as candidate-drift evidence and start a new root from a clean
  commit. Never interpret downstream semantic or file-integrity failures from
  that root as independent product defects.

### A reported GUID must not be parsed as a Volume value

- Evidence: #60 native-Windows r30 returned the exact four requested Sound
  rows, paths, languages, notes, and `-4.0`, `-2.0`, `-3.0`, and `-1.0 dB`
  values. The Agent also included each requested Sound GUID in its table. The
  object-query oracle scanned every number on the row, interpreted GUID digit
  groups as additional Volume values, and falsely failed all four rows.
- Prevention: the paired object-query oracle extracts Volume only from an
  explicit finite number immediately labeled `dB`. Identity numbers in GUIDs,
  names, paths, or other columns remain independent evidence and cannot affect
  the Volume comparison. Preserve exact row identity, pairing, language, notes,
  order, exclusions, and the single expected dB value; do not weaken those
  business assertions to accept arbitrary numeric prose.

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
