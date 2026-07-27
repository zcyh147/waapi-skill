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
  that canonical surface plus the five fixed `ak.wwise.ui.commands.*` URIs;
  it is not a complete Authoring reflection. Profile counts are packaged route
  contracts, not claims that every row dispatches on the named host: all five
  UI-command routes require Authoring, including rows retained in older Console
  manifests. Live `getInfo.isCommandLine` selects the profile automatically.
  Never add a caller-controlled live profile override.
- Prefer deterministic code and structured results over prompt-only knowledge.
  When a capability is unavailable through the packaged interface, return a
  clear boundary instead of teaching the model how to synthesize a workaround.
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
    reads, subscriptions, transaction phases, result ceilings, and
    `session_context`.
- `skills/waapi-skill/wwise_waapi/`
  - implementation library. Important seams include `capabilities.py`,
    `execution_contracts.py`, `operation_registry.py`, `transactions.py`,
    `transaction_runtime.py`, `transaction_cleanup.py`, `io_policy.py`,
    `dispatcher.py`, `subscriptions.py`, and the semantic builders.
- `skills/waapi-skill/resources/manifest/<version>/`
  - reflected Console functions, topics, schemas, immutable inventory
    metadata, and the narrow `authoring-ui-commands-supplement.json` and
    `authoring-ui-command-inventory.json` resources.
- `skills/waapi-skill/resources/deferred/<version>.json`
  - category and deferred-route classification.
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
- Update README coverage numbers and `tests/TEST_INVENTORY.md` only from an actual
  completed run; never estimate a passing count.
- Fresh Codex campaign and matrix runners are the only agent-semantic test lane.
  Do not add a second harness or mix evidence from unrelated agent runtimes.

## Testing ladder

Start with the cheapest lane that proves the change. Expand only when the
changed behavior requires it.

### 1. Focused program tests

Run the directly affected pytest files while iterating. Then run the fixed
five-version program gate from the repository root:

```bash
ci/test.sh --mode program -- -q -ra
```

This gate uses fake clients and must not start Codex, WwiseConsole, or
a network client. For ordinary API-surface expansion, this is the required main
gate; do not spend tokens on a full semantic matrix merely because rows were
added to the same established mechanism.

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

The official profiles are `screening` (40 sessions), `formal_98` (98), and
`full_cross_version_168` (168). Run the latter two only when the user explicitly
requests that expense or a release criterion requires them. A partial, quota-
blocked, or infrastructure-blocked campaign is not a semantic pass. Read
`tests/semantic/README.md` before running any campaign.

For harness-only CI checks that start neither Codex nor Wwise, use the focused
pytest commands in `tests/semantic/README.md`.

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
