# Implementation batches and checks

Use this sequence for the current coverage implementation. Historical acceptance
belongs in [the test inventory](../../../tests/TEST_INVENTORY.md); current Fresh
scheduling and failure classification belong in [business acceptance](../../../tests/semantic/TEST_ACCEPTANCE.md).

The 2026-10-23 test-selection and evidence-reuse rules in that document govern
batch planning and reruns. Each active ticket's execution note identifies its
next complete business flow, reusable checks and remaining native evidence.
The five-version scope and existing blocking edges remain unchanged.

Use the current checkpoint to name one ticket as the closeout focus and list
its remaining acceptance steps with existing evidence pointers. Finish already
reviewed work and required dependencies alongside it; assign new independent
work only when it advances that ticket. Keep other obligations assigned to
their original tickets. Report whole-ticket completion separately from merged
components, without changing the original acceptance criteria.

For a shared mechanism repair, inspect the complete operation's declared
changes and its affected consumers before handoff. Review that mechanism and
its caller evidence together. Later reviews concentrate on unresolved findings
and changed behavior; reuse previously checked source and evidence instead of
recopying or rereading unchanged archives. Publish one consolidated handoff per
integration batch.

Every agent dispatch must explicitly set `fork_turns="none"`. Send only the
objective, constraints, acceptance criteria, relevant document/code pointers and
essential decisions not yet recorded. Require descendants to use the same rule;
do not copy parent conversation history into a dispatch.

Derive native API names, fields, enums and request shapes from the matching
version and host's WAAPI reflection. Reuse complete pinned captures; collect
missing schemas or live property/reference metadata before implementing them.
Use matching primary documentation for semantics the reflection does not state.
If behavior remains uncertain, use one minimal owned native case before building
the wider verifier or history machinery. Simulated clients must follow these
sources; passing a simulated test does not establish native behavior.

For a new compound harness protocol, trace the actual task runner through prompt
provenance, request materialization, Broker execution, task-result sealing and
campaign replay before expanding its test matrix. First prove one complete task
through those existing consumers, stubbing only the external Codex process for
the pure-code check. Reuse its authenticated receipts for focused corruption and
retry-prefix controls. Lower-level Broker passes alone do not prove that the
task can produce and replay its final result.

Before running a new or changed native collector, apply the final-report-writer
check in `tests/semantic/TEST_ACCEPTANCE.md` section 3. Collector-only checks do
not establish that the native attempt can save its final acceptance record.
The handoff must point to the persisted success record and a retained partial
failure from that check. Reuse those records while the collector and relevant
consumers remain unchanged. If only the report writer fails, repair and test
that writer against retained input before considering another Wwise run.

Each repair assignment lists the failed pytest node IDs and directly affected
callers, with a reason for any additional selection. Use explicit nodes after
`ci/test.sh --mode nonlive --` (or the matching real version/mode). The launcher
replaces native defaults when explicit paths/nodes are supplied; `-k` alone
filters the default selection. Do not use `--mode focused` for a repair: it is
the historical alias for the full real matrix. After the selected checks pass,
handoff and stop; a final repeat of green tests is not a separate acceptance step.
If a check fails, keep the passing results and select only the failed and newly
affected nodes after the fix. Any broader gate belongs to the stable batch below.

1. Freeze one bounded batch of explicitly selected immutable worker refs. Workers
   run their relevant focused cases; changed preparation or verification also
   selects its affected existing public-route matrix rows. Confirm negative tests reach the
   intended boundary from a valid baseline. Keep later successors separate and
   merge only the selected refs with one integration source owner.
2. Identify which generated artifacts the batch actually changes. Reconcile
   their reviewed source seals before regeneration; preserve unchanged artifacts
   and evidence. When both inventories are affected, finish
   `tests/maintenance/generate_interface_depth_inventory.py`, then generate
   `tests/maintenance/branch_coverage_audit.py`; use their `--check` modes to prove
   the final artifacts are current. Preserve all native IDs, owners and evidence.
   A documentation-only change does not itself call for inventory regeneration
   or recapturing native behavior. Keep unvalidated source-dependency changes
   explicit until the affected checks establish that reuse is valid.
3. Deduplicate the affected selection and run one proportional combined focus
   for behavior beyond the preflight. Keep each original verdict bound to its
   tested candidate; an unchanged worker check need not be repeated wholesale.
4. Publish the merged, reconciled candidate and use the PR's automatic
   `ci/preflight.py` run as the fixed batch preflight. Inspect its terminal
   result on the exact published commit; do not duplicate it locally before
   pushing. It runs existing roster/schema seals,
   the complete fake public-route matrix and actual Tone terminal-output controls
   through `ci/test_driver.py`. It takes no selection overrides and launches no
   Wwise or Codex. The PR workflow uses the same command with Python 3.11 and
   locked Poetry dependencies. Use `poetry run python ci/preflight.py` locally
   only when CI is unavailable or diagnosing a specific CI failure requires it.
   This is a cheap development guard, not full Program acceptance or a
   requirement for every small worker handoff.
5. During development, run only failed and affected cases. Run required full
   Program and Non-live gates after the integration batch is stable.
   Keep source unchanged while tests run and wait on the same live process
   handle; report terminal results, new failures or decisions. Inspect source
   only after the owned group ends. Record exact results and unresolved work;
   preserve failed evidence.

Keep one current resume index in the ignored coordination directory, with each
component's exact commit, terminal result path, review status and next action.
After restart, inspect those receipts before scheduling work; uncertainty in a
handoff is not grounds to repeat a completed test. Review changed hunks and
unresolved risks, using bounded result/log reads rather than entire evidence trees.

The workflow has read-only permissions, cancels superseded PR runs and uses only
the official [checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1)
and [setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0)
actions pinned to their full release commit IDs. Local preflight success does not
prove hosted CI, Windows or native-Wwise acceptance.

## Opt-in developer batches

Use the existing launcher with exactly one JSON plan path; batch selection is
separate from the unchanged `--mode program` and ordinary mode entrypoints:

```bash
ci/test.sh --batch-plan /absolute/path/to/batch.json
```

A minimal non-live plan is:

```json
{
  "contract": "waapi-skill.test-batch/v1",
  "root": "/absolute/path/to/new-batch-root",
  "groups": [
    {
      "id": "launcher",
      "mode": "nonlive",
      "version": "none",
      "host": "none",
      "nodes": ["tests/unit/test_ci_test_bat.py::test_python_driver_owns_all_platform_defaults_and_pytest_nodes"],
      "sources": ["tests/unit/test_ci_test_bat.py"],
      "depends_on": []
    }
  ]
}
```

Plans contain 1–64 ordered groups, each with those seven fields and 1–256
explicit test selectors. `sources` lists the finite relevant repository files;
the driver also fingerprints selected test files and its shared batch plumbing.
`depends_on` names earlier groups. Repeated selectors and compatible duplicate
groups share original outcomes. Ordinary test failures block their dependents
while independent groups continue; source, evidence or cleanup faults stop
further dispatch. This is an explicit dependency map, not automatic discovery of
all callers.

Every attempt needs a fresh absolute, unaliased `root`. Repository-local roots
must be below `.waapi-skill-state/`. `summary.json` links per-node original
results and records failures, reuse and the next selection. Child pytest roots
live beneath this durable root, so later default pytest retention cannot prune
them. Preserve failed roots and original receipts.

Add `"previous": "/absolute/path/to/old-root/summary.json"` to a new-root plan
to select failed and affected tests. Unchanged passes are reused only after
reopening their exact original terminal receipts, source/context and outcomes.
Relevant source or native-context changes select affected groups and declared
dependents. Unmapped changes produce `unknown_impact` and block dispatch; a
new hash or documentation edit alone does not establish equivalence. Optional
`irrelevant_changes` maps changed paths to explicit reviewed reasons and cannot
override relevant source files. Source planning neither rewrites historical
hashes nor issues a new PASS for retained results.

For an interrupted report, use
`"recover_from": "/absolute/path/to/old-root/summary.json"` with the same
declared groups and a fresh root. This reporting-only path executes no producer
and cannot combine with `previous` or `preflight_evidence`. It reconstructs
validated saved terminal completions with their original source/verdict. A
persisted not-started fact can leave a group BLOCKED/`NOT_STARTED`; missing,
unsafe or started-without-terminal evidence stays BLOCKED/`UNKNOWN`. A later
`previous` plan may run proven unstarted/failed/affected work while retaining
completed siblings; unknown execution requires resolution before replay.

Native batch admission is deliberately limited to the existing
`tests/destructive/test_gateway_workflow_transaction_matrix.py::test_console_owned_runtime_read_batch`
selector, with `mode: destructive`, `host: wwise-console` and one pinned version
per group. Versions run sequentially through the existing owned lifecycle;
singleton collectors retain their isolation. The driver first inserts the
existing collector-to-final-consumer checks. Optional `preflight_evidence` is
an original summary descriptor, `{"artifact": "/absolute/path/to/summary.json",
"sha256": "<original SHA-256>"}`: it reopens the complete consumer receipts and
checks relevant sources before reuse. It does not replace native semantics
review or relax source/cleanup requirements.

Keep the durable report root separate from the physical native sandbox parent.
The latter follows existing `WWISE_TEST_CONFIG` / `WWISE_SANDBOX_ROOT`
configuration, with unique lifecycle-owned copies. For example, an explicitly
short owned `WWISE_SANDBOX_ROOT=/private/tmp/waapi-batch-console-new` may accompany
a deeper durable root. The admitted Console workflow validates source/sandbox
separation and projects its fixed fixture path before dispatch; paths exceeding
the existing 260 UTF-16-unit Windows/Wine limit, including NUL, are blocked.
The authoritative live path guard remains in force. A representative native
batch and focused developer passes do not replace the prescribed final gates.
