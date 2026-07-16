# Fresh Codex semantic validation

The formal agent-behavior gate is the resumable fresh Codex campaign in
`tests/semantic/run_codex_skill_campaign.py`. It delegates execution to the v2
matrix runner in `tests/semantic/run_codex_skill_matrix.py`, tests the installed
`waapi-skill` through its packaged gateway, and grades the suite in
`skills/waapi-skill/evals/evals-v2.json`.

Mocked pytest is CI-safe contract coverage. It is not a replacement for a
fresh Codex conversation or real WwiseConsole semantic validation.

## Memory-off isolation contract

Every phase starts a new Codex CLI process, thread, and turn. The runner creates
disposable `HOME` and `CODEX_HOME` directories, links only the selected
`auth.json`, exposes exactly one target Skill, and audits the prompt for memory
markers. A phase fails its hard gates if memory, user skills, extra reads,
repository discovery, ad hoc code, or unbrokered gateway commands appear.

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

From the repository root, run each profile into a distinct campaign directory.
Use the Skill-local Python so the runner-owned live fixture has the same pinned
`waapi-client` dependency as the packaged gateway:

```bash
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile screening --campaign-root skills/waapi-skill-workspace/campaign-screening
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile formal_98 --campaign-root skills/waapi-skill-workspace/campaign-formal-98
skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile full_cross_version_168 --campaign-root skills/waapi-skill-workspace/campaign-full-cross-version-168
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
agent action is classified and archived as a Codex infrastructure failure. It
does not count as a Skill pass or a Skill failure, but the profile remains
incomplete and the runner exits non-zero. Once the agent has acted, a
service-looking error remains subject to normal semantic grading.

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
```

Passing these mocked/offline tests does not prove live semantic capability.
