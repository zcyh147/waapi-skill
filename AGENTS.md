# Repository guidance for AI agents

This repository implements `waapi-skill`: a local, version-aware WAAPI interface
for Wwise Authoring. Read this file before changing the Skill or running tests.
`tests/AGENTS.md` adds more specific rules for files below `tests/`.

## Design intent

- The Skill is the interface layer. It replaces an always-on MCP server with a
  packaged local gateway, versioned resources, and explicit behavior guidance.
- The public execution path is
  `skills/waapi-skill/scripts/run.py gateway.py ...`. An agent using the Skill
  must not write temporary Python, call `WaapiClient` directly, invent a WAAPI
  payload, or bypass a structured gateway boundary.
- Support is intentionally version-pinned for Wwise `2021.1`, `2022.1`,
  `2023.1`, `2024.1`, and `2025.1`. Do not assume that a URI or schema is
  identical across versions.
- The canonical `wwise-console` execution profile is the five-version
  WwiseConsole reflection. The separate `wwise-authoring-ui` profile is only
  that canonical surface plus the five fixed `ak.wwise.ui.commands.*` URIs
  and separately pinned observation Topics and approved core/selection/project
  functions for 2024.1/2025.1;
  it is not a complete Authoring reflection. Profile counts are packaged route
  contracts, not claims that every row dispatches on the named host: all five
  UI-command routes require Authoring, including rows retained in older Console
  manifests. Live `getInfo.isCommandLine` selects the profile automatically.
  Never add a caller-controlled live profile override.
- Prefer deterministic code and structured results over prompt-only knowledge.
  When a capability is unavailable through the packaged interface, return a
  clear boundary instead of teaching the model how to synthesize a workaround.
- Judge migration depth at the public Gateway interface. Every supported named
  operation and non-named lane must expose the accepted Gateway-owned business
  seam or an explicit prohibited/host/version boundary. Historical PASS
  evidence, a small request, an existing dedicated route, or a syntactically
  typed request does not establish that migration; generated inventories must
  retain and assign those rows until their caller interface is uniformly deep.
- Read-only work should be direct and bounded. Every project change uses an
  immutable preview, at most one execution, and verification. `read_only`
  blocks changes but still permits catalog-proven read transactions;
  `ask_before_changes` presents the expected result and waits for a later
  explicit confirmation; `allow_changes` gives notice and may continue from a
  distinct durable policy authorization in the same user turn. A
  design-only or ambiguous request never receives direct policy authorization.
- The first Skill-backed reply uses gateway-owned `session_context` for the
  natural one-time introduction. Do not add a separate live call only to produce
  that introduction, and do not reconstruct its facts from memory or prose.

## Architecture map

- `skills/waapi-skill/SKILL.md`
  - trigger description, agent behavior, fixed gateway routes, no-code rules,
    one-time introduction, and setup/query/operate routing.
- `skills/waapi-skill/scripts/run.py`
  - thin launcher with an immutable packaged-script allowlist and Skill-local
    virtual environment.
- `skills/waapi-skill/scripts/gateway.py`
  - the public CLI contract: offline catalog/config commands, bounded live
    reads, the closed business-declaration and separately disclosed advanced
    `query-schema` contracts behind `query-object`, subscriptions, transaction
    phases, result ceilings, and `session_context`.
- `skills/waapi-skill/wwise_waapi/`
  - implementation library. Important seams include `capabilities.py`,
    `execution_contracts.py`, `operation_registry.py`, `transactions.py`,
    `transaction_runtime.py`, `transaction_cleanup.py`, `operation_drafts.py`,
    `operation_composer.py`, `io_policy.py`, `dispatcher.py`,
    `subscriptions.py`, `metadata_discovery.py`, `metadata_cache.py`,
    `builders/query.py`, and the remaining semantic builders.
    `operation_drafts.py` owns mutable, capability-bound composition state;
    `operation_composer.py` owns typed operation-local actions and deterministic
    materialization. Neither replaces the immutable transaction preview or its
    authorization and verification.
  - `operation_registry.py` is the authoritative Gateway entrypoint for named
    structured operation contracts. Reviewed exact reflected-URI business
    lanes use their version-aware business contract registry (currently
    `core_business_contracts.py`) and the Gateway `request-schema` path instead.
    Builder or dispatcher support alone does not expose either kind of
    operation: its public request shape, version scope, safety behavior, and
    verification boundary must be present through the matching registry and
    Gateway schema path. The reflected-URI lane still materializes its native
    `args` and `options` inside the Gateway; callers never author them.
- `skills/waapi-skill/resources/manifest/<version>/`
  - reflected Console functions, topics, schemas, immutable inventory
    metadata, and the narrow `authoring-ui-commands-supplement.json` and
    `authoring-ui-command-inventory.json` resources.
    `authoring-ui-topics-supplement.json` adds only `selectionChanged`,
    `signal.click`, and `signal.toggle` where matching Authoring reflection
    established their absence from Console. It does not expose other UI APIs.
- `skills/waapi-skill/resources/deferred/<version>.json`
  - category and deferred-route classification.
- `skills/waapi-skill/resources/metadata/<version>/object-types.json`
  - compact, reflected object-type discovery index; live property/reference
    metadata remains authoritative for discovery and mutation validation.
- `skills/waapi-skill/resources/native_surface_policy.json`
  - complete function-route partition plus detailed selector mapping for the
    high-risk reflected request surfaces that differ from their public closed
    operations; `normalized_equivalent` claims also require focused operation
    tests.
- `skills/waapi-skill/resources/semantic/<version>/` and `resources/waql/<version>/`
  - compact runtime semantic evidence and versioned query examples.
- `skills/waapi-skill/references/waapi-*.md`
  - the only lane references loaded by the current agent-facing Skill.
- `skills/waapi-skill/evals/evals-v2.json`
  - frozen historical fresh-Codex semantic suite and the 40/98/168 profiles.
- `skills/waapi-skill/evals/suite-v3.json`, `online_tests.json`,
  `offline_tests.json`, `adapter_registry.json`, and
  `request_mapping_registry.json`
  - review-oriented definitions for the five-version unique executable URI
    union (not all version/API rows). Online means a real sandboxed Wwise
    connection; offline cases receive no functional coverage credit. The
    approved `heavy_cross_version_80` subset has implemented adapters and a
    completed sealed real campaign recorded in `tests/TEST_INVENTORY.md`; the
    rest of V3 remains review material rather than executable evidence.
    Adapter names outside the implemented subset are specifications, not
    implementations. A v3 scenario listed under any unresolved request-mapping
    requirement is blocked from execution; never guess an enum number,
    unresolved token, structured request shape, or missing route.
- `tests/`
  - program, non-live, live, destructive, and agent-semantic validation.

The packaged `skills/waapi-skill/references/semantic/` tree is the sole canonical
human-readable source evidence for the five version lanes. There is no separate
repository-root reference mirror. NotebookLM may be used to refresh offline
source material, but it must never become a runtime dependency.

## Adding a Wwise version

Keep a new-version change small but complete. Do not copy a prior lane and call
it supported without proving the reflected and executable surfaces:

1. Reflect the matching WwiseConsole functions, topics, and schemas; collect the
   narrow Authoring UI-command supplement separately when that overlay is in
   scope.
2. Add the versioned manifest inventory and required deferred, metadata,
   semantic, and WAQL resources, with immutable counts and digests derived from
   the new reflection. Review the versioned business-query schema and extend
   the Gateway-owned declaration compiler, advanced-contract goldens, and
   fail-closed negative matrix when the new version changes any supported
   source, relationship, business predicate, output, native expression, or
   result-bound rule.
3. Classify every new or changed route in its execution lane and update the
   capability, execution-contract, operation registry, adapter registry,
   request-mapping registry, and native-surface policy entries that actually
   apply. A named structured mutation is not public until
   `operation_registry.py` exposes its closed contract. A reviewed exact
   reflected-URI mutation is not public until its business contract registry
   exposes the closed request through Gateway `request-schema`; raw native
   `args` and `options` remain internal in both cases.
4. Update README coverage and test-inventory documentation only from generated
   inventories and completed runs; distinguish a reflected route, a
   program-tested route, and real execution evidence.
5. Run focused tests and extend the full supported-version program gate first,
   then run the matching live and destructive lanes. Add a targeted fresh-Codex
   semantic case only where routing, prompt behavior, or a new integration
   boundary needs agent evidence. Run real versions sequentially and record
   blocked prerequisites instead of treating them as passes.

## Configuration and local state

Public persistent configuration lives outside the installed Skill, in this
order:

1. `$WAAPI_SKILL_CONFIG_PATH`
2. `$XDG_CONFIG_HOME/waapi-skill/config.json`
3. `$HOME/.config/waapi-skill/config.json`

Use gateway `config-show` and `config-set`; do not hand-edit configuration.
`skills/waapi-skill/data/config.json` is ignored legacy fallback data, not the
normal write target.

Do not commit local/generated state such as `.venv/`, `__pycache__/`,
`.pytest_cache/`, `.coverage`, `.waapi-skill-state/`, test sandboxes,
`skills/waapi-skill-workspace/`, or the machine-specific
`tests/fixtures/local/live-environment.json`. Existing evidence or campaign
directories may be valuable even though ignored; never delete them without the
user's approval.

## Change rules

- Preserve unrelated user changes and avoid destructive Git commands.
- Keep `SKILL.md` lean and route detail into the four current `waapi-*.md`
  references. Do not reintroduce broad repository research into normal Skill use.
- Treat `waapi-operate.md` as the compact cross-operation control plane.
  Operation-specific fields, nested shapes, and version deltas belong in the
  version-aware `operation-schema` or `describe` result; do not add per-API
  Markdown merely to repeat structured gateway contracts.
- Keep mutation identities free of caller- or model-authored raw WAQL. Object
  reads use two public layers: the closed business declaration returned by
  offline `query-schema`, then—only when that declaration cannot express a
  required server-side read semantic—the bounded
  `waapi-skill.advanced-object-query/v1` contract disclosed by
  `query-schema --advanced`. The business declaration subsumes the former
  shortcut and structured-Builder inputs; do not restore a public
  `waapi-skill.object-query/v1`, raw predicate/return grammar, or typed-
  structured fallback. The advanced contract fixes
  `ak.wwise.core.object.get`, owns its return projection and final `take`, and
  never becomes a raw args/options or mutation path. Mutation identities remain
  limited to `id`, `path`, `exact-type-name`, `direct-child`, and
  `scoped-name`. An advanced query cannot certify target uniqueness: before a
  later change, present its candidates, obtain the user's exact choice, and
  verify that chosen GUID through the simple exact-ID query route before using
  the normal closed mutation contract. Candidate projections keep unaliased
  `id`, `name`, `type`, and `path`; the exact-ID readback must match the chosen
  name/type/path or the workflow stops. The advanced schema is explicit about
  UTF-8 byte limits and one trimmed, single-line frame: comments, semicolons,
  and unclosed string or slash-regex literals are rejected before dispatch.
  The same per-object exact-ID readback applies when a broad business or
  advanced query returns multiple candidates and the user later selects only a
  subset for mutation. It does not apply to a canonical relationship GUID
  used directly as the next read-only hop.
- Keep successful ordinary `query-object` replies compact by default. The
  compiled semantic preview and dispatch evidence are an explicit `--detail`
  diagnostic view; do not rerun a successful live query merely to obtain that
  detail. Failures retain their complete bounded evidence, and both projections
  must preserve the exact final `agent_result` object.
- Prepared-role revalidation deduplicates canonical GUIDs into one
  `MULTI_IDENTITY_READ_MAX_IDS`-bounded object read. Reject an oversized set
  before dispatch, and fail closed on missing, duplicate, extra, or malformed
  rows before applying the stored per-role field comparisons.
- Identity and property-metadata reuse inside operation preparation is
  preview-local. Key identity results by the exact canonical selector and
  property metadata by its exact object/class scope and field token, reset both
  caches for every new preview, and never let either replace execution-time or
  verification-time live state checks.
- Generalize “business declaration → controlled native expression” only to
  fixed read-only APIs with a declarative DSL whose time, row, and byte
  boundaries remain Gateway-owned. Do not copy the native
  expression fallback to project mutations, SoundEngine commands, topics,
  SoundBanks, imports, UI commands, or Lua/code execution; extend their closed
  contracts instead.
- Keep `agent_result` exact for machine-readable replies. Do not rebuild it from
  summaries, and preserve its final insertion-order position in gateway payloads.
- All live results and structured failures must stay bounded. Cleanup failures,
  timeouts, ambiguous mutation outcomes, and result-schema-only verification must
  remain distinguishable.
- A Topic execution contract's `timeout_seconds` is its packaged default or
  recommendation, not a caller maximum. `wait-topic` defaults to 10 seconds,
  honors an explicit positive finite `--timeout`, and accepts `--no-timeout`
  only as an explicit event-count-bounded wait. Even without a time limit,
  event count, result size, terminal JSON output, cancellation cleanup, and
  Authoring-host boundaries remain enforced.
  A requested event count or per-event output selects `stream-topic`, without
  an implicit total timeout. Streams without explicit total duration default to
  300 idle seconds; only matching events restart the clock. `--idle-timeout`
  overrides it; `--no-idle-timeout` disables it. Explicit total duration has no
  implicit idle cutoff. Idle termination is incomplete count monitoring, not
  target completion. The 64-event cap is Skill-owned.
- A new reflected API row needs an explicit public route or exclusion, versioned
  schema validation, safety classification, and program coverage. Same-count URI
  substitutions must fail the inventory digest checks.
- Authoring UI command-ID inventories are host/project/plugin/add-on evidence
  snapshots, never runtime allowlists. Execution and registration decisions
  must use a fresh bounded `ak.wwise.ui.commands.getCommands` read. If these
  resources need refreshing, use
  `tests/maintenance/collect_authoring_ui_commands.py`; do not broaden the
  collector beyond live `getInfo`, the five fixed schemas, and `getCommands`
  without a new review.
- A new mutation route needs a closed request schema, immutable preview artifact,
  confirmation or policy-authorization binding, drift checks, non-retry
  semantics, and an appropriate verifier or an explicit weaker boundary.
- A Windows `next_command.shell_command` is the fixed encoded PowerShell argv
  envelope from `wwise_waapi/platform_commands.py`. Do not replace it with
  `subprocess.list2cmdline`, `cmd.exe` quoting, or model-reconstructed argv;
  `list2cmdline` is a CreateProcess/MSVCRT serializer, not a CMD shell escape.
  A v2 continuation may additionally expose a short Gateway-generated
  `model_command`; execute only the field named by the complete
  `copy_instruction.source_field`. The encoded `shell_command` remains the
  canonical audit/fallback envelope and is not selected implicitly.
- Update README coverage numbers and `tests/TEST_INVENTORY.md` only from an actual
  completed run; never estimate a passing count.
- Fresh Codex campaign and matrix runners are the only agent-semantic test lane.
  Do not add a second harness or mix evidence from unrelated agent runtimes.

## Testing ladder

Start with the cheapest lane that proves the change. Expand only when the
changed behavior requires it.

Repository development and ordinary test execution use the Poetry environment:
invoke `ci/test.sh`, which delegates to Poetry, rather than installing project
test dependencies into the Skill environment. The packaged Skill runtime and
formal semantic campaigns instead use `skills/waapi-skill/.venv`; do not replace
that interpreter with Poetry or a global Python. This keeps developer tooling
independent from the minimal environment shipped to Skill users.

### 1. Focused program tests

Run the directly affected pytest files while iterating. Then run the fixed
five-version program gate from the repository root:

```bash
ci/test.sh --mode program -- -q -ra
```

This gate uses fake clients and must not start Codex, WwiseConsole, or
a network client. For ordinary API-surface expansion, this is the required main
gate; do not spend tokens on a full semantic matrix merely because rows were
added to the same established mechanism. For the business query compiler,
five-version Python validation, compiler goldens, gateway fake-dispatch tests,
and fail-closed negatives prove the closed declaration contract. They do not
prove that a newly added advanced WAQL construct has been accepted by a real
Wwise process.

### 2. Broad non-live regression

Before merging a substantial runtime, contract, or documentation change, run:

```bash
ci/test.sh --mode nonlive -- -q -ra
```

Use `tests/TEST_INVENTORY.md` for the current scope and last recorded results.

### 3. Real Wwise validation

Real modes require a matching WwiseConsole and SampleProject configured in the
ignored `tests/fixtures/local/live-environment.json` (copy the committed example
first). Run only the version and risk level needed by the change:

```bash
ci/test.sh --version 2022.1 --mode smoke
ci/test.sh --version 2022.1 --mode live -- -q -ra
ci/test.sh --version 2022.1 --mode destructive -- -q -ra
```

Use `--version all --mode matrix` only for an explicitly requested cross-version
release gate. Versions run sequentially; never launch the real matrix in
parallel. Destructive tests must use sandbox projects and the existing lifecycle
manager, never a user's authoring project. See `tests/AGENTS.md` for prerequisites
and evidence rules. A successful macOS run is not Windows validation; claim
Windows support evidence only from an actual Windows host. A missing prerequisite,
skip, or blocked lane is not passing evidence; report it explicitly and fail
closed where the contract requires proof.

### 4. Real Authoring reflection maintenance

Refresh the fixed UI-command supplement only against an already-running,
matching Wwise Authoring process, one version at a time:

```bash
skills/waapi-skill/.venv/bin/python \
  tests/maintenance/collect_authoring_ui_commands.py --version 2025.1
```

This developer-only collector is the narrow exception to the public Skill's
no-direct-client rule. Per version it performs exactly seven read-only calls:
`getInfo`, `getSchema` for each of the five fixed UI-command URIs, and
`getCommands`. It must never execute, register, or unregister a command. Its
command-ID inventory is an environment snapshot, not an allowlist. This
maintenance evidence does not prove a UI business effect and is not part of
the Console live/destructive matrix.

The offline `capabilities --profile wwise-authoring-ui` and
`describe <uri> --profile wwise-authoring-ui` options inspect the packaged
overlay only. They are not configuration fields and cannot override live host
detection.

### 5. Fresh Codex CLI semantic validation

Use this lane for changes to `SKILL.md`, routing, first-use behavior, exact output
handling, or no-code/no-bypass behavior. Do not evaluate from an existing Codex
app conversation. The formal campaign creates a fresh CLI process, thread, and
turn for every phase; uses disposable `HOME` and `CODEX_HOME`; links only the
selected `auth.json`; injects exactly one Skill; and audits memory isolation.

Prepare the pinned local interpreter if needed:

```bash
python skills/waapi-skill/scripts/setup_environment.py
```

For a cheap, narrow offline probe, select an existing case and explicitly use
the lower-cost model/settings rather than relying on the campaign defaults:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py \
  --profile screening \
  --case-id C1 \
  --offline-only \
  --model gpt-5.6-terra \
  --reasoning-effort medium \
  --service-tier default \
  --campaign-root skills/waapi-skill-workspace/campaign-c1-terra
```

For a targeted real-Wwise semantic case:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py \
  --profile screening \
  --case-id Q2 \
  --version 2022.1 \
  --model gpt-5.6-terra \
  --reasoning-effort medium \
  --service-tier default \
  --campaign-root skills/waapi-skill-workspace/campaign-q2-2022-terra
```

Use a new campaign root whenever the Skill, suite, harness, live config, Codex
binary, interpreter, model, or immutable options change. Resume an unchanged
campaign with `--resume`; use `--resume --verify-only` to recheck sealed evidence
without starting Codex or Wwise.

On Windows, formal campaigns require the standalone Codex CLI. Discovery
prefers the official user-owned standalone locations, then checks `PATH`, and
accepts only a hashable real `.exe` that passes a direct `--version` probe. It
rejects `%USERPROFILE%\.codex\.sandbox-bin` and skips protected Microsoft Store
`Program Files\WindowsApps` executables that cannot be launched as child
processes. Install the standalone CLI or pass its exact real path with
`--codex-binary`; do not substitute a `.cmd`, `cmd.exe`, or `shell=True` launch.
Because campaigns ignore user configuration, native Windows execution must also
pin Codex's `windows.sandbox` backend to `unelevated` while retaining
`workspace-write` and approval policy `never`. Omitting that backend leaves the
managed-filesystem policy without a sandbox implementation and can decline the
first non-safe Gateway command before it reaches the authenticated broker.
Formal Windows campaigns also require an attested PowerShell Core `pwsh.exe`
version 7.3 or newer with `Standard` or `Windows` native argument passing. The
campaign seals its path, version, mode, and SHA-256, forces a profile-free shell,
and uses Broker-owned `python.ps1` / `python3.ps1` relays. Never restore the old
`.cmd` relay: PowerShell intentionally uses legacy argument passing for batch
files and can remove structural quotes from Gateway JSON before Broker
authentication. Before PowerShell attestation or Codex launch, the native
harness sets and reads back Console input and output code page 65001; a failure
blocks before the Fresh turn. Skill reads use the exact literal form
`Get-Content -Raw -Encoding UTF8 <path>` and receive credit only through the
sealed PowerShell Core wrapper.

The official profiles are `screening` (40 sessions), `formal_98` (98), and
`full_cross_version_168` (168). Run the latter two only when the user explicitly
requests that expense or a release criterion requires them. A partial, quota-
blocked, or infrastructure-blocked campaign is not a semantic pass. Read
`tests/semantic/README.md` before running any campaign.

The public integration-acceptance profile is `integration`. It runs six
prewritten workflows once on Wwise 2022.1 and once on 2025.1: 12 fresh
memory-off Codex tasks, 36 user turns, and 20 separately previewed transactions.
The workflows are Weather construction, Alarm diagnosis and repair, Harbor
SoundBank release, Rifle reimport, Footsteps Switch-assignment maintenance, and
query-guided Weapons cleanup. It uses `gpt-5.6-terra`, medium reasoning, the
default service tier, the formal campaign harness, and sequential execution.
The committed fixed-baseline graph and media apply only to Rifle, Footsteps,
and Weapons. Freeze the first pass, consolidate ordinary case failures, and
only then repair and start a new campaign root. This is cross-operation
integration acceptance; it grants no additional per-API coverage credit.

Run the public profile with the Skill-local interpreter and a new explicit
campaign root; its default composed suite means no public `--suite` is needed:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py \
  --profile integration \
  --model gpt-5.6-terra \
  --reasoning-effort medium \
  --service-tier default \
  --campaign-root skills/waapi-skill-workspace/campaign-integration-new-candidate-r1
```

The older `integration_workflows_cross_version_6` and
`integration_workflows_v2_cross_version_6` names remain internal compatibility
profiles for sealed history and replay. Their roots are component evidence,
not a unified `integration` campaign and not a single-candidate 12/12 result.

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

Pre-review public `integration` candidate
`ebcfde245bcbcacd2b8842e5ec205e7111b86743` passed all 12 units in one fresh
root on each host: macOS `imac-int-ebcfde2-r67-full12` and native Windows
`iwin-int-ebcfde2-r56-full12`. Both roots then passed identical
`--resume --verify-only`. Across the 24 PASS lifecycle records, source-project
full hashes and mtimes remained unchanged, passing sandboxes were removed, and
final scoped-process checks were empty. The macOS LaunchAgent and Windows
`InteractiveToken` / `Limited` Scheduled Tasks were deleted. This is
independent single-root 12/12 evidence on both hosts, not cumulative repair-root
credit. Review-repair code candidate
`170e8e8f01cd5e931933c6fe76baff47d0683f57` later hardened playing and
transport capability stores against Windows reparse points and resolved
non-stable object-set batch `--field` names through live metadata, so the
earlier root remains truthful evidence but is not final-candidate acceptance
for that successor. That successor passed macOS Program 4737 / 2 skipped,
native Windows Program 4714 / 25 skipped, and macOS Non-live 10322 / 113
skipped / 27 deselected. Batch-order repair candidate
`fd2f9ed2c9fd2336e76545b1aef6f0ce4e99acfe` then passed macOS Program 4738 /
2 skipped, native Windows Program 4715 / 25 skipped, and macOS Non-live 10325 /
113 skipped / 27 deselected before its targeted Weapons reruns.

Final semantic-harness candidate
`0682c1a979f7ce5bfb648914914b7393148a6495` keeps the packaged Skill tree
byte-identical to `0edaf1a` and accepts permutations of independent existing-
object edit rows while still rejecting missing, extra, duplicate, or changed
objects, fields, handles, and values. Native-Windows root
`iwin-int-0682c1a-r63-full12` passed the public `integration` profile 12/12 in
one root plus identical verify-only. MacOS root
`imac-int-0682c1a-r73-full12` passed 11/12; only INT22 Rifle stopped before
Preview after the Agent incorrectly called an explicit
`complete=true, truncated=false` response truncated. Fresh queued root
`imac-int-0682c1a-r74-int22-rifle` then passed that sole unit plus identical
verify-only without any code, suite, harness, or option change. MacOS therefore
has same-candidate cumulative 12/12 evidence, not a single-root 12/12 claim.
Every source hash and project mtime remained unchanged, passing sandboxes were
removed, the failed sandbox stayed sealed, and all temporary LaunchAgents,
Scheduled Tasks, and Wwise processes were cleared.

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

For Switch assignments, runtime candidate
`d05f1ecdc3b33fca83866e75669c65039877edd6` passed the final macOS and
native-Windows Program gates, macOS Non-live, and the closed add/remove
workflow on native Windows Wwise 2022.1/2025.1. Route-only candidate
`d45f75f5e75190d5b4e607a02aee2dcf38e73ab9` then passed macOS Program and
the same real workflow on macOS 2022.1/2025.1. Fresh roots
`imac-sab-d45f75f-r2` and `iwin-sab-d45f75f-r2` each passed the one-unit
`switch_assignment_business_1` profile plus identical
`--resume --verify-only`. Earlier `d05f1ec` roots on both hosts remain
frozen FAILs because the Agents invented operation aliases; the Broker rejected
them before Gateway or Wwise dispatch. No Fresh root executed a mutation, all
temporary launch resources were removed, and scoped residual-process checks
were empty.
After the entry Skill was compacted, exact packaged-Skill candidate
`b544197fb6b7455814fbb2079043a5a354daca59` repeated the same one-unit PASS
plus identical verify-only in macOS root `imac-sab-b544197-r1` and
native-Windows root `iwin-sab-b544197-r1`. Both roots retained sealed attempt
manifests, started no Wwise process, executed no mutation, removed their
temporary launch resources, and ended with zero scoped residual processes.

Final deepened Switch-assignment candidate
`c874917220cb7723d60f86a14cea72c5d15cca52` passed the one-unit profile
fresh plus identical `--resume --verify-only` in macOS root
`imac-sab-c874917-r1` and native-Windows root `iwin-sab-c874917-r1`.
Both Agents followed the Gateway-owned copy-ready `draft-start`, then the fixed
`switch_container`, `child`, and `state_or_switch` role continuations into one
Preview; no Wwise process or mutation occurred. The Windows Fresh and replay
used temporary `InteractiveToken`/`Limited` Scheduled Tasks. Both hosts ended
with zero scoped residual processes and Windows retained zero matching tasks.
Exact Program candidate `4c55ba6b53eeb4beff97e7b590686d78da7e612e`
passed macOS 3659 / 2 skipped and native Windows 3646 / 15 skipped; later
`c874917` changes only semantic evidence/protocol tests. MacOS Non-live at
`d10dc23c4dd95eb865a5a768ac8a4e0885e6a233` passed 8639 / 110 skipped /
27 deselected. The later packaged diffs are bounded to copy-ready business
start/role continuations and compact audio-import receipts, covered by exact
focused regressions (410 passed at `4389b6c`, 452 / 4 skipped at `4c55ba6`,
and 76 passed at `c874917`); Switch native dispatch and verification did not
change. Frozen Mac diagnostic root `imac-sab-d10dc23-r1` stopped after a
successful schema read without issuing `draft-start`, received no PASS credit,
and was not replayed.

The completed 2026-07-31 macOS integration evidence is cumulative across frozen
campaign roots, not one final-candidate 6/6 run. The initial `a12` root passed
both Alarm and Harbor workflows on both versions and failed both Weather
workflows. Fresh repaired roots `a20-int22-weather` and
`a24-int25-weather` then passed the two Weather units. Thus all six unique
profile units have passing evidence across those roots; do not report that
`a12` itself passed 6/6 or that all six were rerun after the final repair.
Every passing sandbox was removed, failed sandboxes were sealed and
quarantined, and both source SampleProjects retained identical full hashes and
mtimes. This older evidence belongs to the candidate before the
structured-query request and closed mutation-selector migration.
The roots named in this paragraph and the 2026-08-03 macOS paragraph below
seal `runtime.platform=darwin`; later cross-host component reruns are recorded
separately.

The 2026-08-03 current-wording rerun is also cumulative, not one final-candidate
6/6 run. `campaign-integration-workflows-v1-terra-20260803-current-r1` passed
five units and failed `INT25-ALARM-DIAGNOSE-AND-REPAIR` before mutation because
the Agent redundantly re-read the Action instead of following the already
returned `Target.id`. The Skill query reference was then narrowed to forbid
that duplicate hop. Fresh roots `r2-int25-alarm-action-hop` and
`r3-int22-alarm-action-hop` passed both Alarm versions on the same repaired
candidate, and both passed `--resume --verify-only`. Weather and Harbor had
loaded only the unchanged operate reference in `r1`; all four passed there.
Thus all six current prompt units have passing evidence across these roots,
but there is still no single repaired-candidate 6/6 campaign. All eight
recorded lifecycles preserved source hashes and mtimes; passing sandboxes were
removed and the one failed sandbox remains quarantined. Those V1 roots do not
validate the newer V2 fixture, routing, or workflow contracts.

Later reruns used the legacy internal
`integration_workflows_cross_version_6` component, not the public composed
`integration` profile. At commit
`9e75a1aea496abcb9ef2a61e1da685adb99f4b01`, macOS root
`imac-wah-9e75a1a-r1` passed all six component units fresh and then passed
`--resume --verify-only`. At commit
`9b4de8f618855091a424700b50ab8b0fd1989270`, macOS root
`imac-wah-9b4de8f-r1` passed five units and failed one, while native-Windows
root `iwin-wah-9b4de8f-r1` passed three and failed three; both failed roots
were frozen without verify-only replay. These results remain exact
six-unit-component provenance and must not be reported as current public
`integration` acceptance or combined into a unified 12/12 result.

The legacy internal `integration_workflows_v2_cross_version_6` component is a
distinct fixed-baseline contract. Its three workflows run once on Wwise
2022.1 and once on 2025.1: six fresh memory-off Codex tasks, 16 user turns, and
eight separately previewed transactions. It is fixed to `gpt-5.6-terra`,
medium reasoning, the default service tier, and sequential execution. The
required business graph and media are fixed in the committed
`tests/_org/2022.1` and `tests/_org/2025.1` SampleProject sources and sealed by
the versioned manifests below `tests/semantic/data/integration-workflows-v2/`.
Never open or mutate either committed source directly. Each campaign unit must
copy it to an isolated sandbox, attest the source full-tree hash and project
mtime before and after the attempt, remove the sandbox only after `PASS`, and
seal/quarantine every failed or indeterminate sandbox. The baseline collector
may inspect only an already-running sandbox copy and must do so through the
public Gateway; it is not permission to use a direct WAAPI client.

The completed 2026-08-03 macOS evidence for that legacy component is
cumulative across frozen roots, not one final-candidate 6/6 run. `r8` passed
both Rifle units, `r12-2022` passed the
2022.1 Weapons unit, `r23-2022-footsteps` passed the 2022.1 Footsteps unit, and
`r24-2025-repairs` passed the 2025.1 Footsteps and Weapons units. Thus all six
unique units have passing evidence across those roots. Passing sandboxes were
removed; failed or blocked diagnostic sandboxes were sealed and quarantined;
every recorded source-project full hash and mtime remained unchanged. This
grants no per-API coverage credit and proves only the exact Rifle, Footsteps,
and Weapons workflow paths, not advanced WAQL or unrelated routes.

The later native-Windows evidence for that legacy component is also cumulative.
At commit `0dfea2b`,
`windows-v2-six-0dfea2b-r1` attempted all six units, passed 2022.1 Rifle,
2022.1 Footsteps, and 2025.1 Rifle, failed the other three, exited `1`, and had
no verify-only replay. At `a516835`, `a516-w22-r1` passed 2022.1 Weapons fresh
and verify-only; `a516-f25-r1` failed 2025.1 Footsteps and was frozen without
verify-only. At `f1b6a51`, `f1b-f25-r1` and `f1b-w25-r1` passed 2025.1
Footsteps and Weapons fresh and verify-only. All six V2 units therefore have
native-Windows passing evidence across these frozen roots, but there is no
single-root or single-candidate Windows 6/6 result.

For harness-only CI checks that start neither Codex nor Wwise, use the focused
pytest commands in `tests/semantic/README.md`.

## Agent skills

### Issue tracker

Issues are tracked in this repository's GitHub Issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

This repository uses a single-context domain documentation layout. See `docs/agents/domain.md`.

## Completion checklist

Before handing off a change:

1. Confirm the public gateway route and version scope are explicit.
2. Confirm no model-authored code or direct client fallback was introduced.
3. Run focused tests and the appropriate gate from the ladder above.
4. Record exactly what was and was not tested; distinguish program-tested,
   fresh-Codex-tested, and live-Wwise-tested claims.
5. Run `git diff --check`, inspect `git status`, and leave unrelated files alone.
6. Do not delete ignored runtime data or campaign evidence as incidental cleanup;
   present a deletion list to the user first.
