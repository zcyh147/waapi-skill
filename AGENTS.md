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
- Prefer deterministic code and structured results over prompt-only knowledge.
  When a capability is unavailable through the packaged interface, return a
  clear boundary instead of teaching the model how to synthesize a workaround.
- Read-only work should be direct and bounded. Project changes use immutable
  preview, later explicit confirmation, one execution, and verification. Never
  turn an imperative user request into same-turn preview plus execution.
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
  - reflected functions, topics, schemas, and immutable inventory metadata.
- `skills/waapi-skill/resources/deferred/<version>.json`
  - category and deferred-route classification.
- `skills/waapi-skill/resources/semantic/<version>/` and `resources/waql/<version>/`
  - compact runtime semantic evidence and versioned query examples.
- `skills/waapi-skill/references/waapi-*.md`
  - the only lane references loaded by the current agent-facing Skill.
- `skills/waapi-skill/evals/evals-v2.json`
  - canonical fresh-Codex semantic suite.
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
- A new reflected API row needs an explicit public route or exclusion, versioned
  schema validation, safety classification, and program coverage. Same-count URI
  substitutions must fail the inventory digest checks.
- A new mutation route needs a closed request schema, immutable preview artifact,
  confirmation binding, drift checks, non-retry semantics, and an appropriate
  verifier or an explicit weaker boundary.
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

### 4. Fresh Codex CLI semantic validation

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
