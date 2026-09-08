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

### Import chunking is transport, not semantic order

- Evidence: #60 r28 macOS submitted the complete Weather import as a legal
  three-row structure chunk followed by a one-row Thunder chunk. Gateway
  accepted both, but the Broker rejected the second because its sealed fixture
  happened to group Thunder with two media rows. Native Windows used another
  legal three-row partition and reached the exact final Preview.
- Cause: the oracle sealed arbitrary groups of three declarations instead of
  the individual import rows. `rows_per_command=1..3` therefore disagreed with
  the formal protocol even though row identity, fields, dependencies, media
  order, and final request were unchanged.
- Prevention: seal one expected step per import row, then let the Broker prove
  each submitted 1..3-row chunk is one unique dependency-ready partition of
  the remaining rows. Turn prefixes cover the complete bounded chunk-count
  range. Duplicate, missing, changed, dependency-early, or media-reordered rows
  remain rejected before Preview.

### Nested Draft continuations need the task-local runner projection

- Evidence: #60 r28 Windows completed all Weather declarations and generated
  the exact Preview, but continuation provenance rejected `draft-check`. The
  compact Draft payload exposed `draft.next_command.model_command` with the
  frozen candidate path while the Agent correctly invoked its detached
  task-local Skill path.
- Cause: Broker projection handled top-level `next_command` and business
  prefixes, but returned early for an operation-Draft envelope before
  projecting a standard `next_command` nested inside it.
- Prevention: recursively project every standard next-command contract inside
  an operation-Draft with the same strict candidate validation used at the
  top level. The selected Windows model command must resolve to the fixed
  task-local runner; malformed or alternate fields still fail closed.

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
  The reopened #59 Windows 2022.1 Topic root exposed the interrupted form: its
  15-second subscription-ACK window killed a slower first-run pip install,
  leaving an existing `.venv` with dependencies but no `waapi-client`. The next
  root skipped bootstrap on directory existence and failed immediately with
  `No module named 'waapi'`; both roots were quarantined with unchanged source
  hash/mtime and zero residual processes.
- Prevention for partial environments: setup writes an atomic readiness marker
  only after the exact requirements install succeeds. The marker binds the
  requirements digest; a missing, stale, malformed, or symlinked marker makes
  `run.py` repair the environment even when `.venv` already exists. Real Topic
  fixtures finish and recheck this setup before Wwise startup and before the
  ACK timer begins. Dependency installation time is therefore never classified
  as subscription latency.

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
  #60 r48 reconfirmed this boundary when the exact closed SaveProject Preview
  passed every structural gate but natural Chinese omitted the literal command
  ID; the reply's explicit “执行预览，未执行，项目未发生任何更改” is sufficient.

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

### Category coverage is not migration-family coverage

- Evidence: #60 r41 began the five-version `typed_input_cross_version_25`
  profile on exact candidate `9303d1d`, but final Spec review proved that its
  25 tasks represented only 13 APIs and omitted the Authoring UI,
  SoundEngine, CLI/Console, runtime/remote/transport, relationship, compound,
  and named Debug families changed by #54, #56, and #57. The macOS and native
  Windows roots were stopped while still partial, frozen without replay, and
  their exact campaign/Codex/Wwise descendants and temporary launch resources
  were removed. A 25/25 result from that profile would still not have met #60.
- Prevention: the release profile declares the exact 19 migration-family IDs
  and one reviewed component task for each. Its loader validates the complete
  task count, unique families, all five versions, component profile, suite
  path, and unit identity before applying any case/version filter. Do not infer
  interface-family coverage from broad labels such as `generic`, `draft`,
  `file_code`, or from the raw task count.

### The semantic oracle must not normalize a forbidden caller mechanic

- Evidence: final #60 Standards review found two passing-oracle shortcuts. Lua
  artifact continuations asked the Agent for one complete
  `--arguments-json` map even though the typed key/value form already existed,
  and object-binding grading treated `<Virtual Folder>Weapons` as equivalent
  to the business name `Weapons`. Both forms made native request/path syntax
  caller-visible while the resulting Preview could still be correct.
- Prevention: Lua maps accept only repeatable `--argument KEY TYPE VALUE`
  facts and retain the existing reserved-key, key-count, and byte ceilings.
  Business object bindings accept exact GUIDs or ordered literal name segments;
  angle-bracket Wwise type prefixes are rejected by the Gateway and no longer
  receive Broker equivalence. New-row semantic kind and name stay in the
  business declaration, while the Adapter constructs the complete typed Wwise
  path.

### Business spelling equivalence can silently restore the native interface

- Evidence: final #60 Spec review found that the Broker still credited
  `Sound SFX` as the closed `sound-sfx` kind and a leading Wwise `\\` as the
  same literal path segment. The resulting Gateway argv could be correct even
  though the Agent had authored the native display type or path syntax that the
  deep business interface intentionally removes.
- Prevention: business-literal equivalence is limited to explicitly reviewed
  business wording such as case-insensitive field meaning. Native Wwise type
  labels, separators, angle-bracket type prefixes, wire tokens, scopes, and
  complete request spellings receive no semantic credit. Test both the
  production rejection and the Broker oracle; a stricter Gateway beside a
  permissive oracle is still a false PASS path.
- Removing a legacy long option is not sufficient while `argparse` accepts
  option abbreviations: `--object-path` can otherwise resolve to the remaining
  `--object-path-segment`. The Gateway parser and every nested subparser require
  complete option names. `draft-bind-object` exposes only exact GUID, repeated
  literal name segments, or the reviewed typed-name selector; the removed
  complete-path spelling fails during parsing before client construction or
  WAAPI dispatch.

### Argv equivalence is not continuation-copy evidence

- Evidence: final #60 Spec review found that the shared business runner only
  reconciled normalized argv. An Agent could therefore reconstruct an opaque
  Draft id, authority, revision, runner path, or shell quoting and still match
  the expected arguments without proving that it copied the unique
  Gateway-issued continuation.
- Prevention: every business runner also binds raw Codex command records to the
  exact preceding Broker payload. The continuation verifier recursively
  recognizes `waapi-skill.business-draft-next-action/v1`, selects exactly one
  copy-ready prefix, and requires those UTF-8 bytes verbatim before any allowed
  typed suffix. Equivalent re-quoting fails on both POSIX and native Windows.
  Top-level `next_command` remains an exact whole-command copy. Normalized argv
  reconciliation still proves semantics, but cannot replace either raw copy
  proof.

### Semantic strictness belongs at the business and safety boundary

- Evidence: the first #60 `deep_business_cross_version_19` roots reported many
  failures because the shared oracle recognized only one reviewed
  `copy_verbatim_then_append_*` action spelling, even when another operation's
  closed copy instruction required the same prefix-copy mechanic. Other cases
  were at risk of treating harmless response wording, synonymous presentation,
  or an irrelevant ordering choice as semantic failure despite a correct
  Preview and unchanged Wwise business result.
- Prevention: hard semantic gates cover the requested Wwise/Preview business
  effect, safety and authorization boundaries, the no-bypass Gateway rule, and
  exact opaque continuation bytes where the Gateway explicitly publishes a
  closed copy instruction. Do not require identical prose, harmless
  terminology, formatting, or presentation order. Order is hard only when it
  changes transaction safety, dependencies, or business effect. Classify
  prefix-versus-exact copy from the complete closed instruction contract rather
  than one operation-specific action suffix; unknown instruction shapes still
  fail closed.
- The one-time introduction still requires every Gateway-owned fact, but the
  product name is natural prose: `waapi-skill`, `WAAPI skill`, and equivalent
  case/space/hyphen presentation identify the same Skill. Requiring the literal
  hyphen produced a false native-Windows Topic FAIL after a complete successful
  subscription and two valid events.

### A business type ambiguity is relevant only when the intent supplied a type

- Evidence: #60 macOS r42 bound the requested `Alarm_Main` object exactly while
  preparing an Output Bus change, then stopped because the shared object-binding
  continuation unconditionally treated the reflected Sound subtype ambiguity as
  blocking. The user had not supplied a Sound subtype and the reference change
  did not require choosing one, so the stop was unrelated to target identity or
  business effect.
- Prevention: compare a resolved business kind when the user supplied a
  business type. If no type was stated, an ambiguous reflected subtype does not
  block an otherwise exact matching name/path binding. Exact identity mismatch,
  an explicitly stated incompatible type, or an operation that genuinely
  requires subtype selection must still stop.
- A role route that fixes both the role and exact Wwise type is also resolved
  evidence. #60 r42 bound `Main_UI` through the disclosed SoundBank exact-name
  route, but the generic semantic-kind table had no SoundBank row and reported
  an empty ambiguity. The Gateway now reports the role as resolved from the
  closed exact-type selector; this does not invent a caller-authored type.

### Compound children defer their own Preview to one parent transaction

- Evidence: #60 r42 correctly checked two closed child Drafts and consumed them
  in one `waapi.undoGroup` parent Preview. The shared immediate-continuation
  oracle nevertheless demanded a Preview after each child and also demanded
  the parent's declaration before the children existed.
- Prevention: the compound profile alone permits the reviewed checked-child
  handoff. It verifies that each deferred child id/authority is consumed by the
  later parent declaration and that the parent declaration copies the original
  opaque parent prefix exactly. Ordinary Drafts still follow their immediate
  `next_command`; this is not a global continuation bypass.

### Business scalar types must be enumerated, not implied by native APIs

- Evidence: #60 r42's Lua Agent saw `--argument <key> <type> <value>` and chose
  the plausible native-looking `int32`, while the business parser accepts the
  JSON-level `integer`. The Broker correctly rejected the command before
  Gateway/Wwise dispatch.
- Prevention: Lua artifact continuations enumerate exactly `string`,
  `boolean`, `integer`, `number`, `json`, and `null`, with compact value rules.
  `integer` explicitly says it is not a native width. Do not rely on a generic
  `<type>` placeholder when the public vocabulary is closed.

### Streamed events need a compact terminal handoff for the Agent

- Evidence: #60 native-Windows r42 received two valid SoundBank generated event
  records and a terminal `event_count=2`, but the Agent reported no events after
  the large Topic schema and NDJSON transcript. This is a real business-report
  error even though the introduction's `WAAPI skill` spacing was a separate
  false-negative oracle.
- Prevention: when the reviewed SoundBank identity shortcut is selected, the
  terminal stream record repeats the already bounded matched identity events in
  final `agent_result`. The live event records remain immediate and authoritative;
  the terminal handoff does not broaden fields, counts, or result limits.
- Follow-up evidence: macOS #60 r44 repeated the real reporting error after the
  terminal handoff existed: the complete command output contained two event
  records plus terminal `agent_result.event_count=2`, while the final prose said
  no event or terminal record was visible. The default SoundBank Topic schema
  was still about 17 KiB before the stream transcript.
- Further prevention: the fixed SoundBank shortcuts now receive a compact
  default `topic-schema`; long-tail row and exact-entry catalogs require the
  explicit progressive `--catalog` disclosure. For every successful stream,
  terminal `agent_result` is the sole natural-language and machine-result
  authority; a positive event count can never be reported as empty.
- Test-harness boundary: a fake stream that deliberately publishes fewer
  events than its requested ceiling completes through its finite timeout. A
  0.5-second unit-test window intermittently processed only one of two queued
  identity events under a loaded full Non-live run, then passed immediately in
  isolation. Use a small but scheduling-tolerant finite window (currently two
  seconds) for that timeout-path assertion; do not repeatedly rerun the whole
  gate and hope the shorter race disappears.

### Natural discovery inference must follow the public first schema step

- Evidence: macOS #60 r44's Audio Import Agent legally ran one `operations`
  lookup, but the shared Fresh helper inferred the optional discovery only from
  `unit.operation`. The import profile stores its route under `scenario.api`, so
  the Broker rejected the lookup before Gateway dispatch while native Windows
  passed the same case by skipping discovery.
- Prevention: after building reviewed steps, derive the optional discovery
  target from the exact first `operation-schema` or `request-schema` argument
  when no explicit override exists. Profile dataclass layout is not part of the
  public business seam.

### “All SoundBanks” must be an explicit business value

- Evidence: #60 r44 exposed both failure branches of an implicit interface.
  macOS skipped discovery and invented the wrong CLI URI; native Windows found
  the exact URI, then encoded “all” as a SoundBank literally named `all` because
  the Gateway represented all banks only by omitting `soundbanks`.
- Prevention: `ak.wwise.cli.generateSoundbank` requires
  `soundbank_scope=all|selected`. `all` forbids a selected list and compiles to
  no native Bank selector; `selected` requires one or more exact names/files.
  Never make an Agent infer business meaning from a missing optional field.

### A sealed witness must use the public request's exact business keys

- Evidence: #60 r43 reached the correct `debug.setAutomationMode` Preview with
  `arguments.enable=true`, but the semantic protocol still expected the retired
  spelling `enabled`. The Broker changed the runner's zero exit to 125 after
  comparing the durable declaration with that stale witness.
- Prevention: build the Fresh witness from the same closed public request key
  (`enable`) used by the operation contract and Preview. A mismatched witness is
  a deterministic harness defect, not an Agent or Wwise failure.

### Optional discovery must not wrap a component's required discovery step

- Evidence: #60 r43's Authoring UI component already begins with one required
  `operations` step. The shared natural-language helper inferred a second
  optional discovery from the unit operation, so Broker construction stopped
  before Codex or Wwise with “optional operations discovery must bind the exact
  first schema operation.”
- Prevention: derive optional discovery only after building the component
  steps. If the first reviewed step is already `operations`, do not add the
  optional wrapper. The one catalog read remains required and singular.

### One exact same-name-root preflight is a valid object-create variation

- Evidence: #60 macOS r43 checked the exact requested `Weather` root path before
  `operation-schema object.create`; native Windows went directly to the schema.
  Both orders are safe and Skill-documented, but the Broker accepted only the
  direct order and rejected the macOS query before Gateway dispatch.
- Prevention: the object-graph profile may optionally accept exactly one
  Gateway `query-object` whose literal segments equal the requested parent plus
  new root name. It remains before the first schema and cannot be replaced by a
  broad query, repository discovery, another target, or a second preflight.

### Final prose must not duplicate every already-proven object marker

- Evidence: #60 macOS r43 produced the exact closed Switch-assignment Preview
  and reported `Snow_Step` assigned to `Surface\Snow`, but omitted the container
  name `Player_Footsteps`; every Broker and business request gate passed while
  the prose-marker gate alone failed.
- Prevention: when the hidden closed request and Preview already prove every
  object and no execution, natural prose needs only identify the result as a
  Preview. Do not require every fixture marker, exact minus glyph, synonym, or
  presentation detail to be repeated.

### Boolean business input must not use positive-or-negative flag prose

- Evidence: #60 native-Windows r43 received explicit `rebuild=false` for two
  SoundBanks, then interpreted the continuation's
  `--rebuild-soundbank|--no-rebuild-soundbank` notation as both flags for each
  Bank. The Broker rejected the duplicated mutually exclusive choices before
  Gateway/Wwise dispatch.
- Prevention: expose one value-bearing form:
  `--soundbank-rebuild HANDLE true|false`; batch rebuild/cache/Init choices also
  take one `true|false` value. Remove the positive/negative aliases so the Agent
  cannot select both branches.

### Temporary desktop launchers must be one-shot in their native vocabulary

- Evidence: macOS #60 r43 used `launchctl submit`; after the campaign stopped at
  a BLOCKED frontier, the submitted job's inferred `keepalive` relaunched four
  times. Each relaunch failed safely because the immutable root already existed,
  but the repeated launcher attempts were unnecessary. On the same round,
  Windows `New-ScheduledTaskPrincipal` rejected the XML term
  `InteractiveToken`; its cmdlet enum is `Interactive` (stored as LogonType 3),
  while RunLevel 0 is `Limited`.
- Prevention: macOS formal Fresh uses a temporary LaunchAgent plist with
  `RunAtLoad=true` and `KeepAlive=false`, then boots it out and removes it after
  exit. Windows uses `-LogonType Interactive -RunLevel Limited`, attests the
  resulting principal as InteractiveToken/Limited semantics, and deletes the
  task after reading exit/evidence. A registration failure before task creation
  is infrastructure setup, not a campaign retry.

### Natural-language business intent may use one documented discovery hop

- Evidence: #60 macOS r42 correctly used `operations` before the Switch
  assignment schema, but the profile expected `operation-schema` as the first
  command and rejected the legal discovery command before any Preview.
- Prevention: a natural-language business request may perform one
  Skill-documented `operations` lookup before its closed schema, even when the
  profile's internal expected operation is a reflected URI. The user did not
  supply that hidden URI, so forbidding discovery rewards guessing. The Broker
  still accepts only the one reviewed lookup followed by the exact expected
  closed schema; an explicit profile override remains authoritative.

### Deep API acceptance must not multiply the first-use prose oracle

- Evidence: #60 r45 native Windows completed the generic object query and
  returned the correct bounded eight-row business result, while macOS completed
  the two-event Topic stream, but each could be marked FAIL solely because the
  first visible reply omitted part of the one-time Skill introduction.
- Prevention: the 19-unit deep-business profile grades route selection, closed
  business input, Gateway evidence, safety, and the real Wwise result. Delegate
  the one-time introduction wording to its dedicated Fresh profile instead of
  multiplying that same prose assertion across every API acceptance unit.

### Natural-language routing may start from the Gateway operation catalog

- Evidence: #60 r45 Agents invented `ak.wwise.ui.commands.project.save` and
  `ak.wwise.cli.soundbank.generate`, and selected generic `object.set` for a
  single-reference mutation even though exact closed routes already existed.
  In #51 r5, however, the Alarm workflow legally began with its reviewed
  `query-object` diagnostic read and was rejected only because the integration
  wrapper had made `operations` mandatory.
- Prevention: permit exactly one initial `operations` lookup when the Agent
  needs routing discovery, or permit the workflow's exact first reviewed step
  when the Skill already closes that route. After either opening, preserve the
  same ordered protocol and closed operation identity. A later user turn that
  confirms one transaction and introduces another operation receives the same
  optional routing checkpoint immediately before that new operation's schema;
  it is not limited to command one of the whole task. Repeated discovery at one
  checkpoint, discovery after its schema, an invented route, or a different
  first business step remains a semantic failure.

### Named business options are transport-order independent

- Evidence: #60 r45 project-setting and SoundEngine Agents supplied every
  correct closed field and value, but placed the target handle after other
  named options. The earlier Broker compared argv groups positionally and
  rejected the otherwise identical business request.
- Prevention: normalize reviewed named option/value groups before comparison.
  Preserve multiplicity, values, required fields, and mutually exclusive
  choices; only their transport order is commutative.

### Topic terminal evidence, not final prose, owns the business truth

- Evidence: #60 r45 captured a complete two-event terminal Topic record while
  the Agent's final prose said that no complete event or terminal record was
  returned. Wwise and the Gateway evidence were correct; the model reconstructed
  the result incorrectly after the command finished.
- Prevention: validate the bounded terminal payload and real Wwise event rows
  directly, and keep the final response requirement to non-empty natural prose.
  Do not inject harness-only markers such as `WAAPI_RESULT_JSON` into a natural
  user prompt. A contradictory summary remains review evidence, but it cannot
  overturn an otherwise exact Topic/Wwise business result.

### Independent compound children may be semantically commutative

- Evidence: #60 r45 applied the requested rename before the requested notes
  change inside the same unexecuted compound Undo Draft, while the canonical
  fixture listed notes first. Both children target different fields, neither
  consumes the other, and the final Preview is identical.
- Prevention: do not count an independent child ordering difference as a
  product failure. Keep dependent children ordered, and retain exact checks for
  child membership, target identity, values, the single compound Undo boundary,
  Preview-only behavior, and final business result.

### The 2021 Debug fixture must expose the project guard row

- Evidence: #60 r42's Debug Agent copied the exact Gateway continuation and
  selected the requested enable action, but the semantic WAAPI shim returned no
  Project for the 2021.1 preflight guard, so the correct path stopped before the
  Preview.
- Prevention: fixture-backed Debug campaigns synthesize the bounded Project row
  required by `from type Project take 1` and `take 2`, including stable id,
  name, type, project-directory path, and `.wproj` file path. This is fixture
  completeness, not Agent semantic credit.

### Current integration coverage must not hide behind archive test names

- Evidence: #51 r1-r3 reached deterministic pre-Agent blockers in current
  Weather transaction planning. The matching end-to-end tests existed under
  `_archive_test_...` names, so pytest never collected them. After those tests
  were restored, #51 r4 exposed that the shared integration wrapper and the
  Weapons workflow still used retired protocol seams despite a green broad
  Non-live run.
- Prevention: every current public integration workflow has at least one
  collected constructibility test that builds its complete protocol and
  validates its workflow plan. An `_archive_test_...` function is historical
  evidence only and must not be the sole owner of a current path. Before a new
  Fresh root, use `pytest --collect-only` or a focused run to prove the named
  current tests are actually collected.

### A running Fresh candidate makes its source worktree immutable

- Evidence: macOS #51 root `imac-integration-a959478-r5` was still active when
  the next harness repair began in the same source worktree. The root was
  stopped, frozen, and denied semantic credit; its Windows peer remained valid
  because it ran from a separate frozen worktree.
- Prevention: after launching a Fresh root, do not edit, format, commit, switch,
  or otherwise change that root's source worktree until it seals and all scoped
  descendants exit. Diagnose from evidence read-only and implement the next
  candidate in a separate worktree. If drift occurs, stop only the exact
  campaign process tree, freeze the root, and start a new root from a clean
  committed candidate.

### Import declaration IDs are opaque but dependency order is semantic

- Evidence: #51 r5 Weather used meaningful task-local IDs such as
  `weather_interactive`, `rain`, and `rain_bed`. The Broker can safely map those
  opaque IDs to sealed IDs, but the expected request listed every container
  before every Sound while the Agent used the natural hierarchy preorder
  parent container then direct Sound. Positional ID mapping therefore rejected
  an otherwise closed declaration before Preview.
- Prevention: compare the resulting parent/child graph rather than forcing one
  presentation order for structure-only rows. Both parent-then-branch preorder
  and all-containers-before-media are valid when every parent still precedes
  its child and the relative order of media-bearing rows is unchanged. Map
  unique task-local declaration IDs from their recursively closed business
  identity; do not require `row-001` prose. Continue to reject child-before-
  parent graphs and reordered media. For numeric business fields such as
  `volume_db`, compare finite decimal value so `-4` and `-4.0` are equivalent;
  field names, integer-only fields, non-finite values, and other business values
  remain exact.

### Optional routing counts are not intermediate turn boundaries

- Evidence: #51 macOS d32381a priority root reached Alarm preparation after the
  workflow added optional `operations` checkpoints. The valid count choices
  shifted the same end-of-turn boundary, but protocol construction interpreted
  one shifted count as cutting through a commutative read group and BLOCKED
  before Codex.
- Prevention: when validating whether a commutative group crosses a turn,
  ignore count variants produced solely by omitting Gateway-marked workflow
  routing checkpoints. The canonical maximum still owns the real turn
  boundary; unrelated shorter terminals remain checked. Keep all count variants
  for Broker/task/archive reconciliation so an omitted routing lookup is still
  sealed exactly.

### Ambiguous business kind matters only when the user asserted a type

- Evidence: #51 Windows r5 Harbor bound the exact Event path and returned the
  matching name, path, and reflected `Event` type. Because Event is outside the
  creation-oriented stable kind vocabulary, `business_kind_resolution` was
  `ambiguous`; the Agent stopped even though the user had not supplied a type
  to validate and the Gateway continuation explicitly allowed it to continue.
- Prevention: if the user stated a business type, compare a resolved stable
  kind and stop on ambiguity. If the user stated no type, exact name/path
  identity is sufficient and the Agent continues with the bound handle. Keep
  this rule identical in the compact operate reference and every Gateway-owned
  object-binding continuation.

### Task-local runner expansion is not parameter reconstruction

- Evidence: #51 Windows r5 Footsteps passed every Broker command through one
  exact installed task-local runner but Codex expanded
  `.agents\\skills\\waapi-skill\\scripts\\run.py` to its exact absolute path.
  The continuation audit alone rejected that command although every Gateway
  argument and opaque token remained exact.
- Prevention: only on native Windows, allow the sealed task-local runner token
  to expand to the Broker-validated absolute installation whose path ends in
  that exact task-local suffix. Re-encode the expected command with only that
  runner substitution and retain byte-exact matching for every other quote,
  token, option, order, and appended business argument. A different runner or
  general re-quoting still fails.

### Import topology equivalence must survive the final Draft replay

- Evidence: #51 d0aabe1 Weather passed the Broker's declaration-graph check on
  both hosts, then the final Preview validator rejected the same graph because
  its durable request placed all structure-only rows before the media rows
  while the sealed witness interleaved each container and Sound.
- Prevention: apply the reviewed topology equivalence at both boundaries.
  Canonicalize structure-only import rows independently of presentation order,
  but preserve the relative order of every media-bearing row. Continue to
  compare paths, types, properties, references, events, media, and all other
  business values exactly after Gateway-owned path/reference normalization.

### A deep exact query owns its default identity projection

- Evidence: #51 d0aabe1 Alarm used the current closed `--path-segment` query on
  both hosts. The Gateway deterministically supplied `id`, `name`, `type`, and
  `path`, but the legacy protocol witness required the Agent to repeat four
  native `--return-field` pairs and rejected the command before dispatch.
- Prevention: treat the deep exact path/GUID form as equivalent only when the
  sealed witness requests exactly the complete default identity projection.
  Never omit or normalize a custom return field, relationship, predicate,
  result bound, broad source, or other query behavior.

### One response may expose two independently closed Draft continuations

- Evidence: #51 macOS 561f4f5 Weather reached the correct Preview, but after
  the import batch it copied the nested standard `next_command` exactly rather
  than the sibling business `next_action_binding`. Both carried complete copy
  instructions and resolved to the same checked Draft command; the audit only
  admitted the business field and recorded a false semantic failure.
- Prevention: when a business Draft payload also exposes a structurally valid
  nested Gateway v2 continuation, accept that selected field as one exact
  candidate. Continue to require byte-exact copying, a complete instruction,
  a matching prior payload, and one unique longest candidate. Do not grant
  equivalent reconstructed argv credit.

### Event Action is one business identity, not Event plus Wwise trivia

- Evidence: #51 561f4f5 Alarm found the exact Event on both hosts but requested
  only its target; Windows Weather later bound the Event itself when the change
  targeted its Action child. The generic deep interface still required the
  Agent to remember `children`, `Action`, `ActionType`, and `Target`.
- Prevention: use the Gateway-owned `event-actions` read preset for one exact
  Event and `event_action_by_event_path_segments` for mutation binding. Gateway
  owns the child traversal, Action type, 100-row bound, action type/target
  projection, and single-direct-child validation. The Agent supplies only the
  Event path or GUID.

### Wwise object names are capabilities, not a universal identity field

- Evidence: #51 macOS 9cb4550 Weather selected the new Event Action binding and
  resolved exactly one live `Action`, but Wwise returned `name: ""` and a
  bracketed path such as `[Play - Rain_Bed]`. The generic handle validator
  rejected the legitimate row before Preview.
- Generalized audit finding: this is not limited to `EffectSlot`. Across the
  five reflected SampleProjects, empty-name public `WObject` rows also include
  embedded values (`Curve`, `Modifier`, `Panner`, `Position`, `RTPC`) and owned
  collection entries (`CustomState`, `MultiSwitchEntry`, `MusicPlaylistItem`,
  `MusicStinger`, `MusicTrackSequence`, `StateGroupInfo`). An Action-only or
  EffectSlot-only exception merely defers the same defect to another family.
- Prevention: keep one reviewed object-identity capability table that declares
  intrinsic, derived, anonymous-slot, embedded-value, and owned-collection name
  modes. Normalize all live object handles through it; GUID, type, absolute
  path, uniqueness, handle digest, and Preview-time readback remain exact.
  Name-dependent operations (`setName`, `object.set` rename, and copy/move
  collision proof) consult the same capability and fail before Preview for
  every type without a mutable intrinsic name. A program-gate audit intersects
  every committed empty-name work-unit tag with the five reflected WObject
  catalogs and requires exact coverage by that capability table. The full set
  is then exercised through handle normalization plus every public name-
  dependent operation, so a new special object cannot hide until a person
  notices it in Authoring. Alarm observers accept the Gateway business aliases
  `action_type`/`target` as exact equivalents of native `ActionType`/`Target`
  and reject conflicting dual aliases.

### A diagnostic hop is one business view, not a hand-built field list

- Evidence: #61 r11/r12 Alarm Agents correctly followed Event to Action to the
  exact target GUID, then requested either a bare Sound identity or only
  `output-bus`. The formal oracle needed the complete Sound routing facts, so
  the Broker rejected those partial reads before Wwise.
- Prevention: `query-object --view sound-routing-diagnostics` owns the exact
  Sound projection (`OverrideOutput`, `activeSource`, and `OutputBus`) and
  returns stable business keys. The `event-actions` result exposes a bounded
  copy-ready continuation for each exact target. The view accepts only one
  exact path/GUID, validates that the live row is a Sound, and cannot be mixed
  with caller-selected fields, predicates, relationships, or result bounds.
- Oracle rule: judge the Gateway-owned business projection, not legacy argv
  length. `--exact-id` and an exact sequence of `--path-segment` values are
  equivalent identity forms, and `--include volume-db` owns the default
  `id/name/type/path` projection plus native `@Volume`. Normalize both forms to
  the sealed witness before comparison; do not fail a correct Wwise read merely
  because the Agent did not restate Gateway-owned return fields.
- The same rule applies when a later Draft binds an object already proved by a
  bounded query: copying its returned GUID and copying the exact returned path
  as Gateway-owned path segments are equivalent. Normalize the path form to the
  sealed GUID only when one prior payload contains that exact GUID/path pair;
  unqueried paths, name-only selectors, and alternate objects remain rejected.

### Omitted business platform means Wwise's unlinked value

- Evidence: #61 r13 Weather bound the correct Action and requested the correct
  `FadeTime`/`Delay` meanings on both hosts, but field binding rejected them
  with `FIELD_PLATFORM_REQUIRED`. The user intent did not select a platform;
  Wwise `isPropertyEnabled` nevertheless requires its native platform argument.
- Prevention: for dependency-bearing properties only, Gateway compiles an
  omitted business platform to Wwise's null GUID when checking the unlinked
  value. The issued Field Handle remains platform-omitted, so later mutation
  semantics are not silently changed to a platform override. Explicit platform
  handles and mismatch checks remain exact.

### A continuation command label must equal its first Gateway argv token

- Evidence: #61 r13 Windows Alarm produced the correct Sound-routing
  continuation, but its descriptive `command` label differed from
  `gateway_argv[0]`. The Broker rejected it as not bound to the sealed runner.
- Prevention: `transaction_next_command` callers use the exact subcommand as
  `command`; human purpose belongs in the surrounding payload. Exact Event
  identity reads now return the copy-ready `event-actions` hop, whose result
  returns the copy-ready `sound-routing-diagnostics` hop, so the Agent need not
  reconstruct either query or its result bound.

### Business meaning qualifiers are not native-parameter drift

- Evidence: #61 r14 Weather used `Play Action Fade Time` and
  `Play Action delay time in seconds` for the exact scope-bound field discovery
  that the protocol labeled `FadeTime` and `Delay`. The Broker rejected the
  harmless wording before Gateway metadata could prove the exact fields.
- Prevention: meaning-only equivalence removes a small reviewed set of object,
  field, and unit qualifiers, then requires one non-empty exact lexical core.
  Negation and unreviewed semantic words remain unequal. The live Gateway still
  binds the exact metadata token and all subsequent field handles, values, and
  native requests remain exact.

### A business query oracle must accept the Gateway's stable result keys

- Evidence: #61 r14 Alarm followed both copy-ready hops correctly on macOS and
  Windows and read the exact Sound, but the observer compared only native
  `OverrideOutput`/`activeSource`/`OutputBus` keys. Production intentionally
  returned `override_output`/`active_source`/`output_bus`.
- Prevention: observers coalesce the reviewed native and business aliases,
  reject contradictory dual values, and compare the resulting exact GUIDs and
  booleans against sealed Wwise state. Stable presentation-key differences do
  not become semantic FAILs.

### A complete JSON reply can still exceed the Agent shell view

- Evidence: #61 r15 macOS Weather correctly bound the second Action, but the
  generic `object.set` post-bind reply repeated the complete long-tail Draft
  action catalog and copy policy. r19 proved the first compaction worked (about
  7.4 KiB), then exposed the same leak one phase later: each two-meaning
  `draft-discover-fields` reply still repeated about 16.6 KiB. r20 proved that
  compaction and then exposed the final common repetition: each successful
  `draft-declare-existing` reply was still about 13.6 KiB.
- Prevention: after `object.set` object binding or field discovery, return a
  sub-8-KiB phase-relevant continuation. Binding retains only the just-used
  selector form, field discovery, existing-object declaration, and one exact
  `draft-inspect` escape hatch. Field discovery retains only repeated discovery,
  existing-object declaration, and that escape hatch. Existing-object
  declaration retains only the next field discovery, an exact one-declaration
  self-loop, completion candidate, and escape hatch. Include the resolved
  object path directly in the compact
  binding receipt; new-object, alternate-selector, and unrelated actions remain
  in `draft-inspect`. New-object declarations keep their operation-specific
  media/list continuations and are not forced through the existing-object
  projection.
  For `object.set` field discovery, emit each candidate once under its requested
  `meaning_results` group; do not duplicate the full same candidate again in a
  top-level list. r22 showed that the duplicate kept real Windows responses at
  about 8.6 KiB after continuation compaction.
  The full capability remains losslessly reachable, but is not repeated after
  every target. Keep a byte-budget regression on the public payload; do not
  treat `response_integrity.complete=true` as proof of model visibility.

### One declaration command owns exactly one task-local declaration

- Evidence: #61 r20 native Windows Weather correctly bound all five Actions and
  discovered the first pair of Action fields, then appended five
  `--declaration-id` groups to one `draft-declare-existing` command. The public
  command is singular and object-scoped Field Handles cannot be reused across
  other bound objects; the Broker failed closed before Gateway or Wwise.
- Prevention: the structured `declare_existing` continuation states
  `exactly_one_declaration_per_command` and requires copying the next response
  revision before the next declaration. The Broker reports that exact repair
  instead of an internal task-local-ID failure. Do not silently split or accept
  a malformed batch: each declaration retains its exact object-scoped handles,
  revision, Preview ownership, and verification boundary.

### Batch counts are derived facts, not Agent-authored checksums

- Evidence: #61 r21 native Windows Weather supplied all nine import rows in the
  correct order but typed `--expected-declaration-count 8`. The Broker rejected
  the otherwise complete batch before Preview. Repeating a deterministically
  countable fact made the interface less reliable without adding authority.
- Prevention: `draft-declare-import-batch` accepts the closed ordered row set,
  row facts, media, Events, and Switch assignments only. Gateway derives row and
  Switch-assignment counts, rejects duplicate/missing row-order identities, and
  records the derived counts in the batch receipt. Caller-supplied count flags
  are absent from the parser and structured continuation. The semantic oracle
  still compares the actual Preview/Wwise outcome with every requested row, so
  removing the redundant checksum does not turn omission into PASS.

### Stable boolean names must state the requested outcome directly

- Evidence: #61 r22 macOS Weather interpreted
  `override_parent_instance_limit` as disabling the parent override and supplied
  `false`, although the user requested that each Sound ignore its parent's
  instance limit. Broker rejected the contradictory value before Preview.
- Prevention: the public field is `ignore_parent_instance_limit`; the requested
  outcome maps directly to `true`, and Gateway compiles the Wwise
  `IgnoreParentMaxSoundInstance` property plus its enabling dependencies. Remove
  the ambiguous old field without a compatibility alias so Agents never choose
  between two spellings of the same behavior.

### Closed business includes are equivalent only after exact projection proof

- Evidence: #61 r15 Alarm reached the exact active AudioFileSource using
  `--include original-file-path --include source-language`; the old protocol
  expected native `originalFilePath` and `audioSource:language` flags and
  rejected it before Gateway. The same mismatch applies to Bus `volume-db`
  versus native `@Volume`.
- Prevention: normalize only the two reviewed complete include sets to their
  legacy witnesses. Source identity, include cardinality, uniqueness, and the
  exact returned fields remain sealed; partial or extra projections remain
  failures.

### Public integration is a Wwise outcome gate, not a repeated prose gate

- Evidence: #61 r16 macOS Weather produced the correct import Preview and
  passed its exact command/transaction gates, but the runner aborted after turn
  one because the natural reply omitted the word naming the Skill. The public
  workflow never reached its later state assertions.
- Prevention: public `integration` delegates first-use introduction wording to
  the dedicated semantic profiles, as the 19-case deep-business acceptance
  already does. It still seals `session_context`, first Gateway use, every
  command, Preview, execute, and Wwise state oracle; only prose omission stops
  aborting an otherwise correct multi-turn workflow.

### A Sound routing view should disclose its exact read-only next hops

- Evidence: #61 r16 Alarm returned exact `active_source` and `output_bus` GUIDs,
  but no continuations. The Agent issued a bare source identity read, which was
  insufficient for the file/language diagnostic.
- Prevention: `sound-routing-diagnostics` returns two bounded copy-ready reads:
  active-source original file plus language, and output-Bus volume. They remain
  ordinary exact-ID business queries and the oracle still rejects missing,
  extra, or contradictory fields.

### Fresh POSIX Draft commands should use the task-local runner

- Evidence: #61 r17 Weather reached the correct declaration but reconstructed
  a nearly correct absolute runner path with one directory segment missing.
  Broker authentication rejected it before Gateway.
- Prevention: as on Windows, project model-visible compact Draft prefixes onto
  `.agents/skills/waapi-skill/scripts/run.py`. Broker validation first proves
  the candidate's absolute canonical command, then rewrites only the runner
  locator; semantic argv and evidence remain exact. Long absolute paths stay in
  sealed audit data, not in text the Agent must reproduce.

### Source and Bus observers need the same stable-key rule as Sound

- Evidence: #61 r17 Alarm copied the source continuation and returned the exact
  AudioFileSource, but the observer still compared only native
  `originalFilePath`/`audioSource:language`; Bus volume has the same `@Volume`
  versus `volume_db` boundary.
- Prevention: coalesce the reviewed source and Bus business aliases exactly as
  for Sound, reject contradictory dual values, and keep sealed path, language,
  dB, and identity comparisons unchanged.

### Draft field discovery is a bounded batch, not one command per meaning

- Evidence: #51 `f0d1945` r10 macOS and native Windows both completed and
  verified the Weather import transaction, then issued one legitimate
  `draft-discover-fields` command for the first Action with repeated meanings
  `Fade Time` and `Delay`. The production parser and live discovery already
  accepted repeated `--meaning`, but the formal Broker protocol still expected
  ten legacy single-meaning commands and rejected the batch before Gateway.
- Prevention: expose `append_repeated` with 1..8 distinct bounded meanings,
  return ordered `meaning_results` with bounded candidates per input, and make
  the formal object.set protocol discover all requested fields for one bound
  object in one Draft revision. Broker and runtime tests must exercise the same
  repeated-meaning command on both shell families; do not repair this by asking
  the Agent to split an otherwise closed batch into more commands.

### A large import stays one Preview but not one unbounded shell command

- Evidence: #61 r23 macOS received a 210-argument Weather import command, but
  the Agent emitted only 95 arguments and silently omitted three rows and their
  Events. Broker completeness rejected it before Preview; no Wwise mutation
  occurred.
- Prevention: `draft-declare-import-batch` appends 1..3 rows per command to the
  same offline Draft. Each response supplies the exact next-revision append
  prefix and the completion check; declaration order and parent references are
  cumulative across chunks. The repeat receipt also states that every row is
  closed in the command that creates it: media, all known requested fields,
  Switch assignment, and Event cannot be deferred to a later chunk. Only the
  final `draft-check` materializes one atomic import Preview. Gateway and Broker
  tests require every requested row, every chunk at or below the bound,
  cross-chunk parent resolution, and one final operation request. Broker
  normalization carries task-local declaration-ID equivalence across chunks,
  so group order and Agent-chosen IDs remain transport while exact parent and
  field meaning stay sealed. A chunk receipt also retains one compact exact-path
  binding route: later rows may bind their Bus, Event parent, or other reference
  dependency between chunks instead of requiring the Agent to predict every
  future handle before the first structure-only chunk. Once all rows are
  present, copy `draft.next_command` directly; do not wrap that already-complete
  copy instruction in a second pseudo-continuation. Do not raise shell limits
  or split the user outcome into separate transactions.

### A declaration receipt must carry the next common construction route

- Evidence: #61 r23 native Windows completed several Action declarations, then
  bound the next Action from memory because the compact post-declaration
  response exposed only another declaration, field discovery, and completion.
  Provenance correctly rejected the unreturned binding command.
- Prevention: after an `object.set` declaration, return one copy-ready shared
  `draft-bind-object` prefix plus the closed ID, path-segment, and Event-Action
  selector forms. The prefix is emitted once rather than duplicated three
  times, keeping the complete response below the Agent-visible byte budget.
  This preserves exact-copy provenance while allowing bind-next,
  discover-next-field, declare-next, or check from the current revision.

### The default operation router must fit one complete Agent-visible frame

- Evidence: #51 macOS `8fcf481` r11 verified the Weather import transaction,
  then stopped safely when default `operations` emitted about 34.5 KB: 33 named
  operation rows plus all 105 request-schema route rows. Broker evidence kept
  the full JSON, but the Fresh Agent's shell view was clipped, so it could not
  safely select `object.set`.
- Prevention: default `operations` returns only each named operation's name,
  business summary, and copy-ready `operation-schema` continuation, with a
  fixed sub-10-KiB program test. The count and `request-schema <api>` template
  remain visible; the complete native route inventory and expanded contracts
  require explicit `operations --detail`. Do not increase Agent tool-output
  limits to compensate for an unnecessarily broad router response.

### Real-test Adapters must consume compact public Draft receipts

- Evidence: the reopened #78 real 2022.1 gate on candidate `03b96bd` failed
  identically on macOS and Windows before the affected mutations dispatched.
  The lifecycle Adapter searched only the retired `fixed_argv_prefix` array,
  while the public continuation intentionally retained only
  `fixed_argv_prefix_copy`. The object-graph fixture likewise searched the
  retired full `draft.declarations` list instead of the exact
  `draft.declared_object` receipt. Both hosts preserved source hashes and
  mtimes, quarantined the failed sandboxes, cleaned their processes, and
  stopped before 2025.1. The next failed-first roots proved lifecycle on both
  hosts, then exposed the same stale assumption one phase later: `object.set`
  field discovery intentionally returns only deduplicated
  `meaning_results[].candidates`, while the real object-graph Adapter still
  searched the removed duplicate top-level `field_candidates` list.
- Prevention: a real-test Adapter decodes the same canonical POSIX or Windows
  copy field selected by its copy instruction, proves the fixed runner/Gateway
  envelope, and applies the existing operation-specific suffix validator. An
  exact copy command must match completely. A new-object result handle comes
  only from the matching compact `declared_object` receipt; internal full Draft
  state is not a public test oracle. For `object.set`, select exactly one handle
  from the requested meaning's single candidate and require the declared
  deduplicated projection; do not fall back to the removed duplicate list.
  Other reviewed single-field operations such as `object.setRTPC` retain the
  top-level `field_candidates` projection, so select exactly one candidate by
  its `matched_meanings` instead of imposing the `object.set` projection on all
  operations. Keep a fast cross-platform regression for both shapes before
  opening another real root.

### Composite Fresh profiles must preserve component contracts

- Evidence: #60 r51 wrapped typed-input and audio-import units in one 19-unit
  profile. Raw matrix PASSes became outer BLOCKED results because the wrapper
  hid component turns and audited dispatch counts, treated the typed runner's
  reviewed `delegated_to_dedicated_profile` introduction marker as missing,
  and passed the audio-import protocol revision into unrelated query, Topic,
  SoundBank, Lua, and Media Pool provenance readers.
- Prevention: a composite unit proxies every component fact consumed by the
  runner or archive validator. Scope a component-specific codec or manifest
  revision by `component_profile_id`; the composite profile id is never a
  substitute. Add one full child-classification test, then reclassify the
  frozen raw matrix read-only before opening a new root.

### Archive import replay must preserve rows while allowing transport chunks

- Evidence: #60 r51 legally transported Weather's three complete import rows
  in one `draft-declare-import-batch`; the canonical archive reconstruction had
  three one-row commands and rejected the PASS as topology drift.
- Prevention: replay archived commands through the same Broker row matcher used
  live. Accept only dependency-ready 1..3-row partitions with unique task-local
  ids; every sealed row, field, media item, reference, order, and final Preview
  must still match exactly. Comparing step-name counts cannot prove this and
  must not replace semantic replay.

### Named business options are groups, not positional arguments

- Evidence: #60 r51 macOS supplied the exact `--notes` and `--object-handle`
  groups in the opposite order from the sealed compound-Undo witness. Broker
  rejected the command before Gateway even though the values and effect were
  identical; Windows happened to choose the canonical order.
- Prevention: normalize only the reviewed unique named groups for that exact
  subcommand, then compare their complete values. Keep fixed prefixes,
  duplicates, unknown options, missing values, and dependent action order
  strict. Cover both orders and one malformed group in Broker tests.

### Omitted and explicit false defaults need one reviewed equivalence

- Evidence: #60 r52 Windows SoundBank generation supplied per-bank rebuild,
  clear-cache, and Init-Bank rebuild groups with the exact default `false`;
  the sealed plan omitted those groups and Broker rejected the otherwise exact
  request before Gateway.
- Prevention: for reviewed SoundBank boolean defaults only, discard an actual
  `false` group when the sealed plan has no matching global option or per-bank
  handle. Preserve explicit sealed groups and reject `true`, duplicate,
  malformed, unknown, or differently targeted groups. Test the positive
  equivalence and a changed-true negative together.

### The compact router must disambiguate business families exactly

- Evidence: #60 r51 Agents confused connected project save with installed UI
  `SaveProject`, Game Parameter range with `object.setProperty`, Profiler data
  capture with a guessed URI, and runtime Event actions with Authoring object
  edits. A query repair also chose the closed `music-segment` kind after the
  live candidate proved exact `MusicSegment`, while the oracle demanded the
  more verbose custom-kind spelling.
- Prevention: keep copy-ready `selection_guidance` for every reviewed ambiguous
  family in the compact default `operations` frame. Accept a stable closed kind
  only when it maps one-to-one to the first exact live candidate; broader,
  guessed, or mismatched kinds remain rejected. Route guidance is a public
  Gateway contract and receives size, exact-selection, and negative tests.
- Follow-up: #60 r54 independently routed the literal Authoring command ID
  `SaveProject` to `ak.wwise.core.project.save` on both hosts even though the
  complete operations payload contained the older unordered guidance. Put an
  exact-command-ID precedence rule before the operation list and make it
  explicitly override connected-project save. The same root also produced two
  host-specific attempts to guess a native URI before `operations`; public
  Skill examples therefore label `request-schema` as accepting only an exact
  user-supplied URI. Broker rejection remains strict and these roots receive no
  PASS credit.
- Second follow-up: candidate `48766d3` made the precedence visible first and
  the next Mac probe selected `ui.commands.execute` correctly, but then skipped
  the still-mandatory catalog hop. That is evidence that more routing prose is
  the wrong seam. Exact Authoring command IDs and capture intent are closed
  fixed routes: expose their named operation schemas directly, omit
  `operations` from the public/Fresh protocol, and retain fresh live command
  inventory validation inside the later Gateway-owned plan. Keep catalog-first
  behavior for all other natural-language mutations.
- The same conflict later repeated for a single `object.setReference`: one Mac
  Agent chose the correct dedicated schema directly and was rejected by the
  catalog-first oracle; the next chose broad `object.set` after the forced
  catalog. Treat the documented one-object rename/notes/property/reference
  mappings as fixed direct routes too. The Gateway still owns identity,
  metadata discovery, opaque field handles, Preview, and verification.
- A later full root showed that “direct” must not mean “reject one exact catalog
  read”: the Agent issued `operations` and stopped at Broker rejection before
  choosing anything. Keep the dedicated schema as the default first step while
  allowing exactly one authenticated catalog prefix bound to that same
  operation. A different route after the catalog remains a semantic failure.
- Apply that seam by operation family, not by one case: the next full root
  repeated the same contradiction for dedicated Notes edits on both hosts.
  Object lifecycle operations therefore use the same direct-default,
  exact-catalog-optional protocol as scalar/reference metadata edits.

### Broker optional prefixes and archive audit must evolve together

- Evidence: #60 macOS r53 first rejected an Object Graph turn that checked the
  requested root before its schema. A failed-first probe then completed the
  exact root query and canonical Preview, and the component runner reported
  PASS, but the outer campaign sealed it BLOCKED as an “unreviewed discovery
  prefix”. The Broker already allowed exactly one root-specific preflight;
  only the independent archive auditor still recognized optional `operations`
  alone.
- Prevention: whenever a Broker adds a reviewed optional prefix, update the
  archive reconstruction in the same change. Match only the complete allowed
  topology: no prefix, `operations`, the exact root query, or `operations`
  followed by that query. Rebuild the exact path segments from the frozen
  business unit and reject a changed root, repetition, reordered prefix, or
  any other discovery. A component `matrix-case.json` PASS is not campaign
  PASS until the independent archive classification agrees.

### Parent-owned Draft starts must pass the complete Broker flow

- Trigger: Compound Undo now creates its children with
  `draft-start-undo-child`. Updating the protocol builder and accepted-command
  list alone left response validation treating only ordinary `draft-start` as
  an authority-issuing command. A valid first child was rejected after Gateway
  returned successfully, before the second child or parent Preview.
- Evidence: `test_broker_completes_parent_owned_children_through_production_gateway`
  reproduced `only draft-start may disclose the task authority` without starting
  Codex or Wwise. The repaired test completes both checked children and the one
  parent Preview through the production Gateway and authenticated Broker using
  the existing business fixture client.
- Prevention: classify start commands centrally; resolve each command's exact
  owning start and read the operation from that start's validated shape. Child
  starts bind a parent but issue a distinct child identity and authority. Their
  subsequent receipts belong to the child, not to the parent or latest sibling.
  Before a Fresh root, run this complete code-level flow as well as the public
  Gateway checks for parent ownership and forbidden independent child Preview.
- Current CUB continuations return the next child start or parent completion
  directly. The current profile uses ordinary exact continuation grading; the
  older checked-child handoff exception is retained only for historical readers.

### One checked Draft response must not expose two executable continuations

- Trigger: native-Windows #60 root `iwin-m60-042bbe2-r67-deep19` passed 11 of
  19 units and failed eight otherwise successful Preview workflows at
  `exact_protocol`. The corresponding macOS root passed 19/19. Windows Codex
  intermittently copied the checked Draft's nested absolute `copy_command`
  instead of the top-level short `next_command.model_command`; both resolved to
  the same authenticated Broker argv and created the correct Preview.
- Cause: the product response exposed both continuations at once, and each
  independently said to copy its selected source field exactly. The Agent had
  to choose between two equivalent executable interfaces even though only the
  top-level continuation was the oracle's canonical choice. This is a shallow
  Gateway seam, not a Wwise, Task Scheduler, Broker, or shell-quoting failure.
- Prevention: after an ordinary Business Draft passes `draft-check`, omit its
  nested executable continuation and expose only the top-level
  `next_command`. A parent-owned Compound Undo child is the narrow exception:
  it has no independent Preview and retains only its parent handoff. Regress
  this through the public Gateway response by requiring one sole continuation
  source, then run the prior Windows failure set before another full root.

### Assert argv structure, not one host's rendered shell text

- Trigger: the exact `acce343` Windows Program gate failed only because a new
  object-lifecycle regression asserted that a copy-ready prefix ended with the
  POSIX text `--role object`. The canonical Windows model command correctly
  rendered the same two argv tokens as `'--role' 'object'`.
- Prevention: tests for Gateway-owned command meaning must inspect structured
  argv when that field is retained, or accept the exact supported rendering of
  each host family when compact projection intentionally retains only the copy
  string. Never treat POSIX quoting as the cross-platform command contract.
- Classification: this is a test assertion defect. It grants no Windows
  product failure and still requires the corrected full Windows Program gate.

### Multi-turn integration PASS must remain independently recomputable

- Trigger: #51 roots `imac-integration-4b15cd4-r1` and
  `iwin-integration-4b15cd4-r1` each completed `INT25-HARBOR` as a three-turn
  matrix PASS with both mutations verified, exact SoundBank artifacts, source
  integrity, and cleanup. The outer Campaign nevertheless sealed the unit
  BLOCKED because archived `gateway_count_exact` and `no_other_commands` were
  present but could not be recomputed from raw evidence.
- Cause: the archive did seal the complete selected step names and per-turn raw
  command evidence. The independent Campaign reconstructor nevertheless passed
  each earlier turn's partial prefix count while selecting that complete lane,
  then incorrectly required the two lengths to be equal. It therefore selected
  an empty protocol for the earlier turns and could not recompute their command
  gates.
- Prevention: validate the complete sealed lane once and permit each monotonic
  earlier prefix to slice it, while retaining exact-name, uniqueness, mandatory
  step, count, and tamper checks. Freeze both affected roots without replay;
  after repair use a new root. Do not rerun Wwise merely to hide the archive
  defect or promote the live matrix result to Campaign credit.

### Closed query discovery must agree with the packaged Skill

- Trigger: #51 candidate `4b15cd4` rejected `query-schema` before the first
  Alarm or Weapons object query even though the packaged query reference
  explicitly permits that bounded schema read before constructing a closed
  business query. The command never reached Wwise and the workflow received no
  semantic result.
- Cause: the older integration protocol encoded only its direct-query lane;
  the Broker therefore treated one legitimate read-only discovery step as an
  unexpected command. A separate Alarm failure similarly used one exact-ID
  readback of the already diagnosed Sound before mutation.
- Prevention: model these reads as individually named optional workflow steps.
  The Broker may select each at most once, requires its exact reviewed argv,
  keeps every mandatory query and mutation step, and seals the selected names
  for independent archive replay. Never permit an arbitrary query-schema or
  query-object command merely because it is read-only.

### Integration observers must consume semantic import batches

- Trigger: #51 `INT25-FOOTSTEPS` submitted all five reviewed import rows in two
  legal chunks of three and two. The Broker authenticated both chunks and
  `draft-check` sealed five complete declarations including the Snow switch
  assignment, but the trusted observer still expected five one-row transport
  calls and rejected the following check as out of order.
- Cause: the Broker correctly treats a 1..3-row chunk boundary as transport,
  while the workflow observer compared raw step positions rather than the
  canonical declaration set and semantic lifecycle milestones.
- Prevention: let the observer advance across only the remaining contiguous
  import-declaration slots when the exact Broker-selected `draft-check` arrives.
  Require at least `ceil(expected_rows / 3)` chunks, retain the maximum of one
  chunk per expected row, and keep execute/verify cardinality plus the final
  real-Wwise business oracle exact. A missing switch assignment, row, or media
  binding remains a semantic failure and cannot be excused as rebatching.

### `useExisting` protocols must distinguish absent import targets

- Trigger: #51 Rifle Fresh units followed the Gateway continuation and bound
  the existing Rifle parent before declaring the requested new
  `Rifle_Distant` Sound. The integration protocol instead demanded a bind of
  the complete absent `Rifle_Distant` path, so the Broker rejected the correct
  command before Gateway or Wwise dispatch.
- Cause: the workflow supplied an `audio.import` request with native
  `useExisting` mode but did not pass its already-sealed pre-state existence
  set to the Composer protocol builder. Without that set the builder must
  conservatively classify every row as an existing target, including the one
  object the fixture explicitly proves absent.
- Prevention: derive `existing_target_paths` from the trusted before-snapshot,
  never from model output. Require each existing row to bind its complete path
  and each absent row to bind only its existing parent, then declare the new
  business name and kind. Regress both forms before another Fresh root; do not
  weaken an exact path bind globally.

### A reviewed query-then-mutate workflow may load both finite lanes up front

- Trigger: #51 `INT25-ALARM` completed the correct diagnosis, exact-ID
  revalidation, Preview, execution, and real-Wwise verification, but failed
  only because it read the already-required `waapi-operate.md` beside
  `waapi-query.md` on turn 1 instead of waiting until turn 2.
- Prevention: for the closed three-turn integration workflows that necessarily
  query and then mutate, schedule those two reviewed references together on
  turn 1. Keep the exact task-local paths, read-before-Gateway ordering,
  one-read-per-reference rule, and prohibition on every other file. This is a
  finite workflow-specific schedule, not permission to preload arbitrary Skill
  documentation or reread a lane later.

### File authority roots are not final output directories

- Trigger: #51 `INT22-HARBOR` copied the workflow's final SoundBank output
  directory into `soundbank.generate --io-root`; the intended authority was
  the higher caller-owned root containing the sandbox project, cache, and all
  generated output. The sibling 2025.1 unit selected that authority and passed.
- Cause: the Gateway continuation described `--io-root` as an "isolated output
  root", which made the containment boundary sound like the final destination.
- Prevention: describe this field as the caller-owned authority root that
  contains project, cache, and every generated output, explicitly excluding the
  final output directory. Keep path containment validation exact; do not accept
  a narrower path merely because the requested Bank files happen to land below
  it.

### Optional routing reads must not become false turn boundaries

- Trigger: #51 candidate `c4cecfd` prepared the complete Alarm fixture, then
  stopped before Codex because adding optional `routing.query-schema` made its
  shorter allowed prefix numerically land inside the three-read commutative
  diagnostic group.
- Cause: protocol validation already discounted omitted `routing.operations`
  rows when deciding whether a group crossed a turn, but did not apply the same
  rule to the equally explicit optional workflow `routing.query-schema` row.
- Prevention: classify both named routing rows as optional insertions when
  deriving real checkpoints. Preserve the complete diagnostic group in the
  selected lane and retain the ordinary rejection for a genuine turn boundary
  inside that group.

### Archive replay must retain all canonical rows behind a merged import call

- Trigger: the same macOS root completed `INT22-WEATHER` with all real-Wwise
  business assertions passing. Its Broker combined nine canonical import rows
  into three legal 1..3-row declarations, but terminal grading compared the
  selected names against an uncontracted workflow and wrote
  `protocol_terminal_passed=false`; Campaign therefore downgraded the PASS.
- Prevention: accept only a prefix contraction of each contiguous import
  declaration block, with `ceil(row_count/3)..row_count` calls, while keeping
  every non-import and selected optional step exact. Independent archive replay
  starts from the full canonical row policy and re-applies the same Broker
  rebatching matcher to the sealed commands. Never validate a merged command
  from only its first row or trust a terminal count without the full row pool.
- A passing scenario removes its owned input WAVs during cleanup. Replaying the
  sealed Draft through the live Store parser then fails before authority or
  request comparison because live parsing correctly requires those files to
  exist. Archive verification must enumerate the complete sealed Draft-record
  set, use the read-only archive codec with cleaned-file evidence enabled,
  verify the stored authority digest, and materialize from that durable session.
  The precomputed offline request is only a fallback when no durable Draft is
  available; it must not override richer sealed state.
- Import contraction and dependency-ready Draft setup ordering can occur in the
  same successful workflow. Candidate `ddd3832` completed macOS Weather with a
  legal three-call import partition, then configured five Action targets in
  bind/discover/declare order per target instead of the canonical all-bind,
  all-discover, all-declare order. Live Broker and matrix grading accepted both
  transformations, but Campaign archive replay tested them as mutually
  exclusive and downgraded the PASS. Archive replay must first prove the closed
  canonical import subset, then validate the consumed order with the same
  dependency-ready step matcher while retaining the full canonical import row
  pool for exact rebatching.

### Metadata meanings are bounded natural language, not magic phrases

- Trigger: macOS #51 Alarm diagnosed the exact broken Sound and target Bus, but
  wrote `Sound output bus` where the protocol had frozen the phrase
  `output bus`. The Broker rejected the semantically equivalent lookup before
  Gateway discovery.
- Prevention: represent `draft-discover-fields --meaning` with the existing
  bounded natural-language argument contract. Mutation authority still comes
  only from the returned live field handle, exact token/kind/scope validation,
  checked Draft, and canonical Preview. Do not require one English phrase when
  the public Gateway deliberately owns synonym resolution.

### Complete Gateway JSON can still overflow the Agent's tool view

- Trigger: repeated native-Windows Weather runs stopped partway through the
  five-Action `object.set` Draft. The last Gateway receipt was valid and
  explicitly reported `response_integrity.complete=true` and
  `truncated=false`, but long Windows campaign paths made the repeated
  continuation large enough that the model-facing shell view was clipped; the
  Agent then correctly stopped and reported a truncated response.
- Prevention: compact public continuations by workflow phase, not only by JSON
  validity. After one existing-object declaration, expose only the next object
  binding, the completion candidate, and the explicit `draft-inspect` recovery
  route. Keep the one copy-ready command named by its copy instruction and omit
  duplicate `fixed_full_argv` arrays. A focused regression caps this receipt
  below 6 KB; durable Draft state and `draft-inspect` retain the full surface.
  The semantic Broker must decode that sole copy field, prove its candidate
  runner and exact argv, then project it to the task-local Skill runner; it
  must not require the deliberately omitted duplicate array.
- The same limit applies after a successful transaction. Windows Weather later
  verified all five Action edits but stopped because the default verify reply
  was about 17.8 KB and repeated full `getProjectInfo` directories/platforms.
  Successful verify replies therefore default to the persisted verification
  digest plus a dispatch-call summary/evidence path, while preserving the exact
  final `agent_result`. Full assertions, readbacks, and ProjectInfo remain in
  durable evidence; failure and indeterminate replies are not compacted.

### Public integration delegates first-use prose to its dedicated profile

- Trigger: #51 candidate `ba0e4a5` produced a real-Wwise PASS for macOS Alarm,
  including a non-empty final response and every business assertion, but the
  outer Campaign changed it to BLOCKED for allegedly missing intro proof.
- Cause: the public `integration` matrix intentionally writes the reviewed
  `delegated_to_dedicated_profile` marker because first-use wording is tested
  by its dedicated semantic profile. Its composed public units did not retain
  that delegation policy, while the archive validator recognized the marker
  only for direct typed-input units.
- Prevention: make the delegation an explicit immutable property of public
  integration units and accept the marker only for a unit that declares that
  property (or the existing typed-input component). Keep the final-response
  and complete business-oracle checks unchanged.

### Windows desktop preflight must be locale- and schema-default-safe

- Trigger: a valid Chinese Windows desktop was falsely reported inactive when
  an SSH preflight searched localized `query user` output for the English word
  `Active`. A replacement Scheduled Task check then mistook an omitted
  `<RunLevel>` XML element for elevated execution even though the registered
  principal reported `Limited`.
- Prevention: prove an interactive desktop from the logged-in user's Explorer
  process with a nonzero `SessionId`; do not parse localized status labels.
  Pass `Interactive` to the PowerShell ScheduledTasks enum and verify that the
  exported task resolves to `InteractiveToken`. Pass `Limited` for `RunLevel`
  and verify `Get-ScheduledTask ... .Principal.RunLevel`; the XML may omit the
  element because LeastPrivilege is the schema default.

### Do not make the Agent repeat object-scoped metadata plumbing

- Trigger: native-Windows Weather bound all five Action objects, discovered
  `FadeTime` and `Delay` for the first Action, then reasonably tried to reuse
  those opaque handles for the other same-type Actions. The Broker rejected the
  command because each handle is intentionally sealed to one exact object GUID.
- Boundary: object-scoped handles must not be made class-scoped merely because
  several current objects share a reflected type. Plug-ins, custom properties,
  enablement dependencies, platforms, and inherited state can make otherwise
  similar objects expose different live metadata.
- Prevention: for three or more ready existing targets, use the Gateway-owned
  `draft-declare-existing-batch` seam. The Agent supplies only bounded
  task-local row IDs, bound object handles, stable business fields, and
  user-facing field meaning/value pairs. The Gateway resolves and revalidates
  every meaning against every exact object, creates separate scoped handles,
  materializes the whole request, and commits one atomic Draft revision. Keep
  the individual discover/declare lane for small or dependency-bearing graphs.
  Once three existing targets are bound and no declaration has started, the
  compact continuation must remove the competing per-object discovery and
  declaration branches: expose only continued target binding or the atomic
  batch. Merely adding a preferred batch beside the old route still lets a
  reasonable Agent select the obsolete sequence and fail before dispatch.
  The Broker must also compare `--field-meaning-value` by the same bounded
  user-facing meaning normalization as live discovery (`FadeTime` and
  `Fade Time` are one meaning here), while keeping row identity and business
  values exact. Otherwise the harness rejects a command the public Gateway is
  designed to accept.
  Live lexical discovery can return both an exact field and weaker related
  candidates (for example `Delay` and a delayed-resume option). The batch seam
  must prefer one unique normalized exact token/display-name match; it must not
  fail merely because bounded retrieval also returned a weaker candidate.
  Time-valued Action fields accept explicit seconds or milliseconds as business
  quantities and normalize them before field-range validation. The Broker may
  equate such units only to the same sealed numeric value; object identity,
  field identity, and the resulting seconds value remain exact.
  Apply the same unique exact-token/display preference to ordinary live field
  discovery: `Volume` must select the exact `Volume` token rather than forcing
  clarification merely because lexical retrieval also found `OutputBusVolume`.

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
