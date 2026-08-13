# Fresh Codex semantic validation

The formal agent-behavior gate is the resumable fresh Codex campaign in
`tests/semantic/run_codex_skill_campaign.py`. It delegates execution to the
existing matrix runner in `tests/semantic/run_codex_skill_matrix.py`, tests the
installed `waapi-skill` through its packaged gateway, and supports both the
frozen v2 profiles and the reviewed V3 profiles described below.

Mocked pytest is CI-safe contract coverage. It is not a replacement for a
fresh Codex conversation or real WwiseConsole semantic validation.

## V3 functional-API review bundle

The historical v2 suite above remains frozen. New functional-API scenarios are
defined by `skills/waapi-skill/evals/suite-v3.json`, which loads two explicitly
named test documents plus closed adapter and request-mapping registries:

- `online_tests.json` means a real, sandboxed Wwise WAAPI connection is
  required. It does not mean internet access.
- `offline_tests.json` contains catalog, schema, version, and unsupported-route
  questions. These cases never receive live functional-API coverage credit.
- `adapter_registry.json` lists every fixture, topic publisher, independent
  oracle, and cleanup identifier referenced by the cases. The registry remains
  specification-only for the full V3 catalog; only the 16 heavy APIs named
  below currently have closed executable adapters in that review bundle. The
  fixed `typed_input_cross_version_25` release profile additionally owns its
  two direct representative seams (`getInfo` and Core Lua); it does not broaden
  the heavy-profile API inventory.
- `request_mapping_registry.json` records natural-language values and complex
  request shapes that the current packaged resources cannot yet map reliably.
  Any listed scenario is blocked from real execution until all of its entries
  are closed; the model must never guess an enum number or unresolved token.

For structured Gateway mutations,
`skills/waapi-skill/wwise_waapi/operation_registry.py` is the authoritative
public operation-contract entrypoint. A semantic builder, fixture adapter, or
dispatcher implementation does not by itself make an operation executable.
The registry-backed `operation-schema` contract must expose the closed request
shape and version scope before a semantic profile may schedule it.

The v3 definitions cover the 198-URI union of executable APIs reflected across
the five supported versions. The coverage unit is one unique URI, not each of
the 808 packaged route-contract version/API rows: shared APIs use 2022.1
scenarios, while the
56 APIs absent from 2022.1 use their earliest reflected later version. The 124
executable APIs present in 2021.1 are also present in 2022.1, so their shared
cases use 2022.1 as the representative execution version. This suite therefore
must not be cited as exhaustive per-version schema or behavior coverage.

The broad 326-case review selection remains pinned to Wwise 2022.1, so APIs
introduced only in later versions have reviewable definitions but cannot
receive 2022.1 evidence. The coverage rule is deliberately strict: every
unique executable API needs at least two different natural user prompts, two
different scenario families, a declared primary API/count/effect, and an
independent business-oracle plan. These are review contracts; exact args/options
predicates and executable adapters come after approval. Setup, cleanup,
supporting readbacks, and case
repetitions do not count. Topic cases require a runner-owned publisher and a
hidden-identity event assertion. Mutation cases require unchanged preview
state, real post-state readback, and scenario-owned cleanup inside a copied
project.

Initial prompts must contain only the user's Wwise requirement. Do not mention
the gateway, evaluation rules, code-generation restrictions, transaction IDs,
or Skill boundaries. A mutation's confirmation is a normal later user turn in
the same fresh, memory-isolated task, for example “预览没问题，按刚才的方案执行。”
Each packaged call gets a separate immutable preview and confirmation, and a
confirmation binds only the currently visible preview. Multi-call business
scenarios repeat a natural scoped confirmation instead of authorizing an
entire workflow in one turn. Persistent Codex memory remains absent; only the
ordinary context of that single disposable task is available.

Dynamic fixture values needed to construct a real request use typed
`visible_inputs` placeholders inside the natural prompt. Examples include
sandbox-local absolute file paths, ephemeral ports, uint64 game-object IDs,
transforms, and profiler cursors. The future runner must materialize every
placeholder before starting Codex and archive the fully rendered prompt. It may
keep independent oracle GUIDs, hashes, control-object identities, and expected
readbacks hidden, but it must never hide a raw required call argument from the
model. Real credentials are not prompt values; use an ephemeral credential
profile or another runner-bound secret reference when an adapter needs one.

The current mapping audit blocks 35 scenario definitions across 21 APIs. These
prompts and business assertions remain part of review coverage, but they are
not runnable coverage. The blockers include integer-backed Sound Engine enums,
Profiler cursor/data-type tokens, unresolved compound object structures, and
log channel/severity mappings. Resolve
them in versioned Skill resources or closed builders after prompt approval;
never place internal enum integers into the natural user prompt.

The 2022.1 review selection contains 326 scenarios for 142 APIs. It consists of
116 single-turn cases and 210 cases using the preview/confirm protocol.
Seventeen cases need more than one separately previewed call, so the selection
requires 230 confirmation turns: 326 fresh tasks and 556 total user turns. The
representative later-version increments add 74 / 27 / 17 tasks for 2023.1 /
2024.1 / 2025.1. The complete reviewed selection is therefore 444 fresh tasks
and 792 user turns. This is intentionally not advertised as a “few dozen” run.
Each case has exactly one primary API; reducing the task count later would
require separately reviewed composite prompts and oracles rather than silently
sharing coverage credit.

The real host is lane-specific. UI cases require isolated Wwise Authoring;
command-line cases require a matching WwiseConsole profile; runtime and
Profiler cases require the owned Sound Engine or capture fixture declared by
the case. A runner must not treat one successful WwiseConsole lifecycle
as evidence for UI or runtime lanes.

Render the full review catalog without starting Codex or Wwise:

```bash
poetry run python tests/semantic/render_v3_review.py --summary-only
poetry run python tests/semantic/render_v3_review.py --version 2022.1 --summary-only
poetry run python tests/semantic/render_v3_review.py --heavy-only --summary-only
poetry run python tests/semantic/render_v3_review.py --heavy-only
poetry run python tests/semantic/render_v3_review.py --api ak.wwise.core.object.copy
poetry run python tests/semantic/render_v3_review.py --case-id OBJ22-F-COPY-01
```

The approved broad executable V3 scope is `heavy_cross_version_80`: five scenarios
for each of 16 APIs, for 80 fresh tasks and 145 user turns. It covers
`object.get/create/set`, `audio.import/importTabDelimited/convert`,
`mediaPool.get`, five SoundBank APIs (`generate`, `generated`,
`processDefinitionFiles`, `convertExternalSources`, `setInclusions`), and the
four reviewed `ak.wwise.cli` APIs. Its representative distribution is 70 cases
on 2022.1, five on 2024.1, and five on 2025.1. Each case receives a fresh
project/process/task and the matrix runs them sequentially.

The focused `compound_heavy_cross_version_24` profile is defined by
`tests/semantic/data/compound-heavy-v1/profile.json`. It runs 12 complex batch
mutation scenarios once on Wwise 2022.1 and once on Wwise 2025.1: two each for
direct import, table import, object create/set, SoundBank generation, and
SoundBank inclusions. Its 24 fresh tasks require 48 user turns when every
preview reaches confirmation. This is a regression profile for request
composition and business assertions, not additional API-coverage credit.

The public `integration` profile is defined by
`tests/semantic/data/integration/profile.json`. It runs six prewritten,
cross-operation workflows once on Wwise 2022.1 and once on Wwise 2025.1. The
closed schedule is 12 fresh memory-off Codex tasks, 36 user turns, and 20
separately previewed transactions. The workflows are Weather construction,
Alarm diagnosis and repair, Harbor SoundBank release, Rifle reimport,
Footsteps Switch-assignment maintenance, and query-guided Weapons cleanup. It
is fixed to `gpt-5.6-terra`, medium reasoning, and the default service tier,
and it reuses the formal campaign, broker, sandbox, evidence, and cleanup
paths. All tasks run sequentially. This profile is integration acceptance
across already reviewed operations; it adds no per-API functional-coverage
credit.

The public profile composes two legacy internal component definitions. The
committed fixed-baseline graph, media, and versioned manifests apply only to
Rifle, Footsteps, and Weapons; Weather, Alarm, and Harbor retain their existing
fixture contracts. Public callers select only `--profile integration` and do
not pass `--suite`. The old `integration_workflows_cross_version_6` and
`integration_workflows_v2_cross_version_6` IDs remain accepted only for sealed
history and replay. Their campaign roots are not unified `integration` roots
and cannot establish a single-candidate 12/12 result.

Treat its first campaign as one frozen pass. Continue after ordinary semantic
case failures so they can be consolidated, then repair once and start a new
campaign root. Stop the pass early only for a systemic harness, source-sandbox,
evidence, or cleanup fault that could invalidate later cases. The profile
totals are a design contract.

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

The legacy internal `integration_workflows_cross_version_6` component is
defined by `tests/semantic/data/integration-workflows-v1/profile.json`. It
supplies Weather, Alarm, and Harbor once per version: six tasks, 20 user turns,
and 12 separately previewed transactions. The following evidence belongs to
that exact component profile rather than the public composed profile.

The completed 2026-07-31 historical macOS evidence is cumulative. The frozen initial
`campaign-integration-workflows-v1-terra-20260731-a12` root passed the Alarm
and Harbor workflows on both versions and failed both Weather workflows.
Fresh repaired roots
`campaign-integration-workflows-v1-terra-20260731-a20-int22-weather` and
`campaign-integration-workflows-v1-terra-20260731-a24-int25-weather` passed
the remaining 2022.1 and 2025.1 Weather units. Across those roots all six
unique units have passing evidence, but there is no single final-candidate
6/6 campaign. Passing sandboxes were cleaned, failed sandboxes were sealed and
quarantined, and all source-project hashes and mtimes remained unchanged.
The roots named in this paragraph and the 2026-08-03 macOS paragraph below
seal `runtime.platform=darwin`; later cross-host component reruns are recorded
separately.

The 2026-08-03 current-wording campaign used the same transaction topology,
fixtures, and business oracles. The full frozen `current-r1` root passed five
units; only the 2025.1 Alarm failed, before mutation, when the Agent repeated an
exact-ID Action read instead of following the `Target.id` already returned by
the Event children query. A narrow `waapi-query.md` repair made that hop
explicit. Fresh `r2-int25-alarm-action-hop` and
`r3-int22-alarm-action-hop` roots then passed the two Alarm versions on the
same repaired candidate and passed their identical `--resume --verify-only`
audits. Weather and Harbor loaded only the unchanged operate reference and
passed in `current-r1`. All six current prompt units therefore have passing
evidence across these roots, but there is no single repaired-candidate 6/6
run. All eight lifecycle records retained identical source hashes and mtimes;
the seven passing sandboxes were removed and the one failed sandbox is sealed
and quarantined. Those V1 roots do not validate the newer V2 fixture, routing,
or workflow contracts.

Later reruns still selected the legacy internal
`integration_workflows_cross_version_6` component, not the public composed
profile. At commit `9e75a1aea496abcb9ef2a61e1da685adb99f4b01`, macOS root
`imac-wah-9e75a1a-r1` passed all six component units fresh and passed its
identical `--resume --verify-only` audit. At commit
`9b4de8f618855091a424700b50ab8b0fd1989270`, macOS root
`imac-wah-9b4de8f-r1` passed five units and failed one, while native-Windows
root `iwin-wah-9b4de8f-r1` passed three and failed three; both failed roots
were frozen without verify-only replay. These results are exact legacy
component provenance, not current `integration` acceptance and not unified
12/12 evidence.

The legacy internal `integration_workflows_v2_cross_version_6` component is
defined by `tests/semantic/data/integration-workflows-v2/profile.json`; its
committed 2022.1 and 2025.1 SampleProject sources contain the fixed `WAAPI Skill
Integration V2` graph and required media. The profile runs these workflows on
both versions:

- safe batch reimport plus one new Rifle variation;
- Footsteps Snow import, Switch Container assignment, and obsolete-assignment
  removal;
- scoped Weapons audit followed by one confirmed batch cleanup.

That is three workflows times two versions: six fresh memory-off Codex tasks,
16 user turns, and eight separately previewed transactions. The runner locks
the profile to `gpt-5.6-terra`, medium reasoning, the default service tier, and
sequential execution. Every unit copies the committed source to its own
sandbox before Wwise starts. The lifecycle compares the committed source's
full-tree hash and project-file mtime before and after the attempt, deletes the
sandbox after `PASS`, and seals and quarantines failed, blocked, retryable, or
indeterminate sandboxes.

The committed baseline manifests record the fixed graph expected in each
source fixture. Refresh one only from an already-running isolated sandbox copy:

```bash
skills/waapi-skill/.venv/bin/python \
  tests/maintenance/collect_integration_workflows_v2_baseline.py \
  --version 2022.1 \
  --live-project /absolute/path/to/sandbox/SampleProject.wproj \
  --write
```

The command is preview-only without `--write`. The collector neither launches
Wwise nor mutates a project; all live reads go through the packaged public
Gateway. It rejects the committed `tests/_org` source (and any overlapping
path), so prepare the sandbox with the repository lifecycle and open that copy
before collection. Collect 2022.1 and 2025.1 separately. A valid committed
baseline is only a fixture prerequisite, not a semantic result. The legacy
Weather/Alarm/Harbor campaigns above do not validate this fixed-baseline
fixture, routing, or workflow contract.

The completed 2026-08-03 macOS evidence for that legacy component is
cumulative across frozen roots, not one final-candidate 6/6 run. `r8` passed
both Rifle units, `r12-2022` passed the
2022.1 Weapons unit, `r23-2022-footsteps` passed the 2022.1 Footsteps unit, and
`r24-2025-repairs` passed the 2025.1 Footsteps and Weapons units. All six unique
units therefore have passing evidence across those roots. Passing sandboxes
were removed; failed or blocked diagnostic sandboxes were sealed and
quarantined; every recorded source-project full hash and mtime remained
unchanged. This evidence grants no per-API coverage credit and proves only the
exact Rifle, Footsteps, and Weapons workflow paths, not advanced WAQL or
unrelated routes.

The later native-Windows campaign for that legacy component is a separate
cumulative evidence chain.
At commit `0dfea2b`, `windows-v2-six-0dfea2b-r1` attempted all six units and
passed 2022.1 Rifle, 2022.1 Footsteps, and 2025.1 Rifle; the remaining three
failed, the outer campaign exited `1`, and no verify-only replay was run. At
`a516835`, fresh `a516-w22-r1` passed 2022.1 Weapons and its identical
`--resume --verify-only` replay; fresh `a516-f25-r1` failed 2025.1 Footsteps on
a metadata-routing detour and was frozen without verify-only. At `f1b6a51`,
fresh `f1b-f25-r1` and `f1b-w25-r1` passed 2025.1 Footsteps and 2025.1 Weapons,
and both passed identical verify-only replay. The final Weapons root reconciled
12/12 Broker records, preserved the exact quoted `@Volume` token, retained an
unchanged source, and removed its passing sandbox. All six V2 units therefore
have native-Windows passing evidence across these frozen roots, but there is no
single-root or single-candidate Windows 6/6 campaign.

The focused `modification_policy_9` profile reuses the existing
`OBJ22-F-CREATE-01` fixture, runner, broker, lifecycle, and business oracle. It
runs `read_only`, `ask_before_changes`, and `allow_changes` three times each:
nine fresh tasks and 15 user turns, all on Wwise 2022.1. `read_only` permits
only the operation-schema read and proves both turns leave the project
unchanged; `ask_before_changes` proves the first turn only previews and asks
for a later confirmation; `allow_changes` requires a concrete user-visible
notice after the authorized preview and before execute. The profile is fixed
to `gpt-5.6-terra`, medium reasoning, the default service tier, CLI approval
policy `never`, disabled memory, and sequential one-shot project sandboxes.

The sealed current-candidate run at
`skills/waapi-skill-workspace/campaign-modification-policy-9-c7` passed all
nine tasks and 15 turns on Wwise 2022.1. It used nine unique memory-isolated
Codex Terra threads. All three `read_only` cases made zero primary mutation
dispatches; all six `ask_before_changes`/`allow_changes` cases made exactly one
and verified seven created objects with 46 passing business assertions. Source
project hashes remained unchanged, every sandbox was cleaned, and a later
`--resume --verify-only` check passed without starting Codex or Wwise.

The reviewed 2022.1 CLI contract keeps conversion and migration mappings
closed. `convertExternalSource` uses explicit platform/path pairs; a shared
multi-manifest, dual-platform union repeats each platform/manifest pair under
`source-by-platform` while remaining one API dispatch. The migration oracle
normalizes the 2021 `Property`/`RTPCList` layout and the 2022
`ObjectLists`/`PropertyName` layout, while still comparing the exact owner,
controlled property, control-input reference, RTPC/Curve identities and flags,
and every curve point.

This executable profile does not make the other V3 definitions runnable. The
remaining catalog still contains specification-only adapters, unresolved
request mappings, UI/runtime/profiler lifecycle requirements, and unapproved
execution surfaces. Do not describe all 444 V3 scenarios or all 198 reflected
URIs as implemented or tested. V2 remains the default suite unless an approved
V3 profile is selected explicitly. Approved executable profiles bind their
packaged default suite automatically; an explicit `--suite` only selects the
reviewed alternate path supported by that profile.

## Memory-off isolation contract

Every v2 phase starts a new Codex CLI process, thread, and turn. Every V3 heavy
scenario starts one fresh process, thread, and memory-isolated task; its natural
confirmation turns remain in that same task and can authorize only the current
immutable preview. The runner creates disposable `HOME` and `CODEX_HOME`
directories, links only the selected
`auth.json`, exposes exactly one target Skill, and audits the prompt for memory
markers. A turn fails its hard gates if
memory, user skills, extra reads, repository discovery, ad hoc code, or
unbrokered gateway commands appear.

Do not run these cases from an existing Codex app conversation and do not copy
the user's normal `CODEX_HOME` into the isolated environment. Memory-off is a
runner-enforced invariant, not a prompt request or an optional CLI flag.

## Official profiles

The profile names and session totals are part of the v2 suite contract:

| Profile | Sessions | Intended use |
| --- | ---: | --- |
| `screening` | 40 | Fast routing and safety gate across transactions, queries, fixed reads, and boundaries |
| `formal_98` | 98 | Repeated formal sample; every unsupported boundary runs three times |
| `full_cross_version_168` | 168 | Full five-version transaction, query, and fixed-read matrix plus one pass per boundary |

The separately approved V3 executable profiles are:

| Profile | Fresh tasks | User turns | Intended use |
| --- | ---: | ---: | --- |
| `heavy_cross_version_80` | 80 | 145 | Real sandboxed business-oracle coverage for the 16 implemented heavy APIs |
| `compound_heavy_cross_version_24` | 24 | 48 | Complex batch composition and real business assertions on Wwise 2022.1 and 2025.1 |
| `typed_input_cross_version_25` | 25 | 39 | Fixed representative typed-input profile: five fresh tasks per Wwise version, no same-root retries, and one public Gateway continuation at each step |
| `integration` | 12 | 36 | Six cross-operation workflows on Wwise 2022.1 and 2025.1; 20 previewed transactions and no additional per-API coverage credit |
| `modification_policy_9` | 9 | 15 | Three isolated repetitions of each canonical project-modification policy on one reviewed object.create business case |

The two older six-task integration profile IDs remain internal compatibility
entrypoints for their exact sealed roots. They are deliberately absent from the
public profile table.

From the repository root, run each profile into a distinct campaign directory.
Use the Skill-local Python so the runner-owned live fixture has the same pinned
`waapi-client` dependency as the packaged gateway:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile screening --campaign-root skills/waapi-skill-workspace/campaign-screening
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile formal_98 --campaign-root skills/waapi-skill-workspace/campaign-formal-98
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile full_cross_version_168 --campaign-root skills/waapi-skill-workspace/campaign-full-cross-version-168
```

Run the approved executable profiles with their reviewed settings; the heavy
profile also supports the bounded pilot selection shown below:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile heavy_cross_version_80 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root skills/waapi-skill-workspace/campaign-heavy-v3-terra
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile heavy_cross_version_80 --case-id OBJ22-F-GET-01 --version 2022.1 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root skills/waapi-skill-workspace/campaign-heavy-v3-pilot-object-get
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile compound_heavy_cross_version_24 --suite tests/semantic/data/compound-heavy-v1/profile.json --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root skills/waapi-skill-workspace/campaign-compound-heavy-v1
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile typed_input_cross_version_25 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root skills/waapi-skill-workspace/campaign-typed-input-new-candidate-r1
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile integration --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root skills/waapi-skill-workspace/campaign-integration-new-candidate-r1
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile modification_policy_9 --campaign-root skills/waapi-skill-workspace/campaign-modification-policy-9
```

`modification_policy_9` is one closed nine-task campaign; its public campaign
entrypoint rejects case and version filters. The matrix receives internal unit
IDs only when the same sealed campaign resumes pending or proven-retryable
work.

`typed_input_cross_version_25` contains exactly five tasks for each supported
Wwise version and covers zero, inline, Draft, generic, dedicated, query, Topic,
metadata, file/code, and weak-verifier UX. It is fixed to Terra/medium/default,
starts one memory-off Agent per task, and forbids same-root pre-action retries.
Freeze ordinary semantic failures and repair them only in a new campaign root
and candidate. A fully passing fresh root may receive identical
`--resume --verify-only` replay; a failed root remains frozen without replay.

Resume with the same profile, filters, candidate, model, reasoning, service
tier, timeout, and retry policy plus `--resume`. Use `--resume --verify-only` to
recheck every sealed artifact without starting Codex or Wwise. A changed Skill,
suite, harness, live config, Codex binary, interpreter, or immutable option
requires a new campaign root; a campaign never overwrites or silently adapts
old evidence.

Each attempt is append-only and SHA-256 sealed. Transaction preview/confirm
phases stay in one attempt and are never spliced across retries. The campaign
runs at most one offline child and one child per selected live Wwise version in
an attempt, so all pending pairs for a version share one scoped Wwise lifecycle.
An early semantic `FAIL` or evidence `BLOCKED` state is sticky. Only a proven
pre-agent-action service/timeout failure is auto-retryable; quota/rate-limit
evidence pauses for an explicit resume, and authentication is `BLOCKED`.

For the heavy profile, one child passes all currently pending or proven
retryable scenario IDs to the same matrix entrypoint. The matrix still runs
each case and Wwise lifecycle sequentially, writes incremental
`run-config.json`, `summary.json`, and `matrix-case.json` evidence, and
continues after an ordinary semantic `FAIL`. It stops on `BLOCKED`,
`INDETERMINATE`, or a systemic evidence fault. A quota/service/timeout failure
is retryable only when runner-authored structured evidence proves that every
earlier turn passed, the broker stopped at that previously proven prefix, and
the failing turn added no command, gateway record, collaboration call, file
change, or invalid event. The campaign also independently binds the task
sidecar and artifact hashes, proves that the source project stayed byte-for-byte
and mtime unchanged, requires cleanup with no uncertainty, and verifies the
never-reuse quarantine against the retained owned-tree digest. Authentication
remains `BLOCKED`. An explicit `--resume` then schedules pending and retryable
scenarios in their original suite order, using a fresh scenario sandbox and
thread; a prior `FAIL` does not erase trustworthy later case results.
`--resume --verify-only` rehashes the immutable Skill, suite, campaign/matrix
runners, Codex binary, Python interpreter, live config, model, options, and
every sealed attempt without starting Codex or Wwise.

Exit status `0` means every selected unit passed, `1` means a trusted semantic
failure, `2` means an invocation/config mismatch, `3` means evidence or runtime
is blocked, `75` means pending/retryable work remains, and `130` is a deferred
interrupt after the active child reached a sealing boundary.

If the local venv does not exist yet, prepare it explicitly with
`python skills/waapi-skill/scripts/setup_environment.py`; the semantic runner
never installs dependencies into the current or global interpreter. On
Windows, use `skills/waapi-skill/.venv/Scripts/python.exe` for the profile
commands.

Useful bounded selections use only options exposed by `--help`, for example:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile screening --case-id C1 --offline-only --campaign-root skills/waapi-skill-workspace/campaign-offline-c1
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile screening --case-id Q2 --version 2022.1 --reasoning-effort medium --campaign-root skills/waapi-skill-workspace/campaign-q2-2022
```

For a precise retry or variance probe, pass the exact suite `--pair-id`. The
child matrix accepts only an atomic `single`, a profile-declared preview-only
unit, or an ordered preview/confirm pair. It rejects confirm-only, reversed, or
filter-excluded pairs.

The defaults discover Codex on `PATH`, use `~/.codex/auth.json`, and load
`tests/fixtures/local/live-environment.json`. macOS alone has a bundled App
fallback. Override them only with the documented `--codex-binary`,
`--auth-json`, and `--live-config` options.

Windows fresh-task campaigns require the standalone Codex CLI. Discovery first
checks the official `packages/standalone/current` and visible user-install
locations, then `PATH`; each candidate must be a hashable real `.exe` and pass
a direct, shell-free `--version` probe. It rejects the outer
`%USERPROFILE%\.codex\.sandbox-bin` proxy and skips protected Microsoft Store
`Program Files\WindowsApps` executables that cannot be started by a child
process. Install the official standalone CLI when no candidate exists, or pass
its exact real path with `--codex-binary`. `.cmd`, `cmd.exe`, and `shell=True`
are not accepted substitutes.

The harness passes `windows.sandbox="unelevated"` explicitly on native Windows.
This is required because fresh tasks ignore user configuration: without a
selected Windows backend, Codex can reject a Python Gateway command at its
execution-policy boundary before PATH resolution or broker authentication.
The fixed backend remains combined with `workspace-write`, approval policy
`never`, and the existing broker boundary; it is not a permission bypass.
Formal Windows runs require a real, non-reparse PowerShell Core `pwsh.exe`
version 7.3 or newer whose native argument mode is `Standard` or `Windows`.
The campaign fingerprints the exact executable, pins `allow_login_shell=false`,
and revalidates that identity for resume and verify-only. Broker command
resolution uses generated `python.ps1` / `python3.ps1` relays with `.PS1` first
in the isolated `PATHEXT`; `.cmd` and `.bat` relays are forbidden because their
legacy argument path corrupts structured Gateway JSON even under current
PowerShell Core. The Skill requires exact
`Get-Content -Raw -Encoding UTF8 <path>` reads. Evidence parsing accepts that
form only from the sealed PowerShell Core wrapper, normalizes line endings, and
tolerates only the single terminal newline added to otherwise complete text.

## Live prerequisites and evidence

Live phases require the exact version-specific WwiseConsole executable and
matching SampleProject configured by the local live-environment file. The
trusted runner owns Wwise fixture creation, sandbox mutation, direct readback,
transaction state, and dispatcher evidence; the evaluated model cannot write
those paths.

For the Rifle, Footsteps, and Weapons units in `integration`, the live config
points to the committed 2022.1 or 2025.1 fixed source, but the lifecycle always
copies that source before launch. The baseline manifest must match the
committed source; Wwise and the evaluated model operate only on the unit-owned
copy. A source full-tree hash or project-mtime drift is a hard lifecycle
failure, not a case failure that may be graded or repaired in place. These
fixed-baseline requirements do not apply to the Weather, Alarm, or Harbor
units.

For the five 2022.1 heavy `ak.wwise.cli.generateSoundbank` cases only, the
trusted prelaunch step makes the private SampleProject copy independent of the
optional ReWwire, Auro, CrankcaseAudio, and McDSP plug-ins. The cleanup is
closed by object identities and an exact Work Unit hash, preserves the Porsche
and built-in Parametric EQ anchors, archives the removed Work Unit inside the
case-owned I/O tree, and emits `project_prelaunch_report` evidence. The clean
pre-setup tree is also the source of the control `business-host` copy. The
immutable source-project full hash must remain unchanged. This normalization
exists solely to make the test fixture portable; it is not a production Skill
fallback and makes no plug-in compatibility claim.

When a selection contains any live phase, the runner first verifies that its
current interpreter can import `WaapiClient` and `WaapiRequestFailed`. A
failure writes `live-preflight.json`, leaves every selected session pending,
prints the exact Skill-venv interpreter to use, and exits before starting a
Codex phase or WwiseConsole. Pure offline selections skip this live dependency
check. The preflight never runs `pip` or changes the global environment.

Each accepted gateway invocation must be authorized by the phase-local broker
and reconciled with the Codex JSON event trace. A semantic assertion failure,
an unexpected read, discovery, file change, or an unbrokered command is a Skill
evaluation failure.

Quota/rate-limit, authentication, timeout, or turn failure detected before any
agent action in the failing turn is archived as a Codex infrastructure failure.
Earlier turns may already have completed, but they and their broker prefixes
must have passed the ordinary hard gates. The old owned
sandbox is quarantined and never reused; a retry restarts the whole case from a
fresh source copy and thread. The interruption does not count as a Skill pass or a Skill failure,
but the profile remains
incomplete and the runner exits non-zero. Once the agent has acted in the
failing turn, a service-looking error remains subject to normal semantic grading.
One narrower exception is an unmatched Codex command lifecycle: if a command
item starts but never receives its matching completion event, the command may
already have affected the disposable Wwise project. The runner archives that
turn as non-retryable `BLOCKED`, quarantines the sandbox, and requires a fresh
case. It never promotes this shape into the pre-agent automatic-retry contract.

The six fixed-read cases cover packaged `status`, `buses`, `selected`,
`metadata types --summary-only`, bounded `wait-topic`, and the reviewed reflection
call. R4 independently recomputes the compact `agent_result` from the complete
runner-owned `getTypes` dispatcher evidence; the evaluated model never receives
the full normalized type inventory. The topic case uses a runner-owned concurrent
publisher after broker authorization;
the evaluated model remains read-only and cannot create its own probe. The
runner supplies the version-specific notification type (`ActorMixer` through
2024.1, `PropertyContainer` in 2025.1) and grades ownership by comparing the
raw event object GUID with the hidden publisher transaction GUID.

The fixed-read argv contract is intentionally closed. R5 requires the
gateway-global prefix `--timeout 10` before `wait-topic`. R6 records explicit
`--args-json '{}' --options-json '{}'` as its canonical form; because both
gateway values default to empty objects, the broker also accepts omitting both
flags together as the same semantic command. Supplying only one flag,
reordering them, or supplying either non-empty JSON object is rejected.

Profile names and expected session totals are test definitions, not proof that
a run completed. Do not claim `formal_98` or `full_cross_version_168` completed
unless every expected phase has accepted evidence and passed its hard gates;
partial or quota-blocked artifacts must be reported as incomplete.

Before sealing a live child, the campaign independently proves that the
recorded WwiseConsole matches the version-pinned live config, the launched
`.wproj` is inside the exact child sandbox, the dynamic WAMP port matches the
command, HTTP is disabled, the immutable source hash and mtime are unchanged,
the launched process exited, and no scoped residual processes remain. A passing
child must have deleted its sandbox; failed or retryable evidence must retain
the real sandbox. Matrix-created Skill symlinks are verified against the frozen
candidate and replaced with regular attestations before the attempt manifest is
sealed. No campaign cleanup uses a global Wwise kill.

## CI-safe focused checks

These checks validate the suite, isolation harness, broker, grader, fixtures,
and documentation without starting Codex CLI or Wwise:

Developer checks use the repository Poetry environment. The Skill-local
`.venv` shown in campaign commands above is reserved for the packaged Skill and
real semantic runner; do not install the developer test stack into it.

```bash
poetry run python -m pytest tests/semantic/test_codex_eval_suite.py tests/semantic/test_codex_harness.py tests/semantic/test_codex_gateway_broker.py -q
poetry run python -m pytest tests/semantic/test_codex_eval_grading.py tests/semantic/test_codex_skill_matrix.py tests/semantic/test_docs_semantic_inventory.py -q
poetry run python -m pytest tests/semantic/test_codex_campaign.py tests/semantic/test_codex_campaign_runner.py tests/semantic/test_run_codex_skill_campaign.py -q
poetry run python -m pytest tests/semantic/test_run_codex_skill_campaign_heavy_v3.py -q
poetry run python -m pytest tests/semantic/test_codex_integration_workflows.py tests/semantic/test_codex_integration_profile_cli_wiring.py tests/semantic/test_codex_integration_workflows_v2.py tests/semantic/test_codex_integration_profile_wiring_v2.py tests/semantic/test_codex_integration_harness_v2.py tests/semantic/test_codex_integration_original_paths_v2.py tests/semantic/test_codex_integration_rifle_runtime_v2.py tests/semantic/test_codex_integration_footsteps_runtime_v2.py tests/semantic/test_codex_integration_weapons_runtime_v2.py tests/unit/test_collect_integration_workflows_v2_baseline.py -q
```

Passing these mocked/offline tests does not prove live semantic capability.
