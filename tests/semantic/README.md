# Fresh Codex semantic validation

The formal agent-behavior gate is the resumable fresh Codex campaign in
`tests/semantic/run_codex_skill_campaign.py`. It delegates execution to the
existing matrix runner in `tests/semantic/run_codex_skill_matrix.py`, tests the
installed `waapi-skill` through its packaged gateway, and supports both the
frozen v2 profiles and the reviewed V3 heavy profile described below.

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
  below currently have closed executable adapters.
- `request_mapping_registry.json` records natural-language values and complex
  request shapes that the current packaged resources cannot yet map reliably.
  Any listed scenario is blocked from real execution until all of its entries
  are closed; the model must never guess an enum number or unresolved token.

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
python tests/semantic/render_v3_review.py --summary-only
python tests/semantic/render_v3_review.py --version 2022.1 --summary-only
python tests/semantic/render_v3_review.py --heavy-only --summary-only
python tests/semantic/render_v3_review.py --heavy-only
python tests/semantic/render_v3_review.py --api ak.wwise.core.object.copy
python tests/semantic/render_v3_review.py --case-id OBJ22-F-COPY-01
```

The approved executable V3 scope is `heavy_cross_version_80`: five scenarios
for each of 16 APIs, for 80 fresh tasks and 145 user turns. It covers
`object.get/create/set`, `audio.import/importTabDelimited/convert`,
`mediaPool.get`, five SoundBank APIs (`generate`, `generated`,
`processDefinitionFiles`, `convertExternalSources`, `setInclusions`), and the
four reviewed `ak.wwise.cli` APIs. Its representative distribution is 70 cases
on 2022.1, five on 2024.1, and five on 2025.1. Each case receives a fresh
project/process/task and the matrix runs them sequentially.

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
URIs as implemented or tested. V2 remains the default suite unless
`--profile heavy_cross_version_80` is selected explicitly.

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

The separately approved V3 executable profile is:

| Profile | Fresh tasks | User turns | Intended use |
| --- | ---: | ---: | --- |
| `heavy_cross_version_80` | 80 | 145 | Real sandboxed business-oracle coverage for the 16 implemented heavy APIs |

From the repository root, run each profile into a distinct campaign directory.
Use the Skill-local Python so the runner-owned live fixture has the same pinned
`waapi-client` dependency as the packaged gateway:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile screening --campaign-root skills/waapi-skill-workspace/campaign-screening
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile formal_98 --campaign-root skills/waapi-skill-workspace/campaign-formal-98
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile full_cross_version_168 --campaign-root skills/waapi-skill-workspace/campaign-full-cross-version-168
```

Run the approved heavy profile with the explicitly reviewed lower-cost model
settings, or start with one pilot case:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile heavy_cross_version_80 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root skills/waapi-skill-workspace/campaign-heavy-v3-terra
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile heavy_cross_version_80 --case-id OBJ22-F-GET-01 --version 2022.1 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root skills/waapi-skill-workspace/campaign-heavy-v3-pilot-object-get
```

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

The defaults point to the Codex binary bundled with the ChatGPT app,
`~/.codex/auth.json`, and
`tests/fixtures/local/live-environment.json`. Override them only with the
documented `--codex-binary`, `--auth-json`, and `--live-config` options.

## Live prerequisites and evidence

Live phases require the exact version-specific WwiseConsole executable and
matching SampleProject configured by the local live-environment file. The
trusted runner owns Wwise fixture creation, sandbox mutation, direct readback,
transaction state, and dispatcher evidence; the evaluated model cannot write
those paths.

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

```bash
python -m pytest tests/semantic/test_codex_eval_suite.py tests/semantic/test_codex_harness.py tests/semantic/test_codex_gateway_broker.py -q
python -m pytest tests/semantic/test_codex_eval_grading.py tests/semantic/test_codex_skill_matrix.py tests/semantic/test_docs_semantic_inventory.py -q
python -m pytest tests/semantic/test_codex_campaign.py tests/semantic/test_codex_campaign_runner.py tests/semantic/test_run_codex_skill_campaign.py -q
python -m pytest tests/semantic/test_run_codex_skill_campaign_heavy_v3.py -q
```

Passing these mocked/offline tests does not prove live semantic capability.
