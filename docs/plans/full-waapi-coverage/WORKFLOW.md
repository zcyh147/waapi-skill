# Implementation batches and checks

Use this sequence for the current coverage implementation. Historical acceptance
belongs in [the test inventory](../../../tests/TEST_INVENTORY.md); current Fresh
scheduling and failure classification belong in [business acceptance](../../../tests/semantic/TEST_ACCEPTANCE.md).

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

1. Freeze one bounded batch of explicitly selected immutable worker refs. Workers
   run their relevant focused cases; a new preparation read also selects its
   affected existing public-route matrix rows. Confirm negative tests reach the
   intended boundary from a valid baseline. Keep later successors separate and
   merge only the selected refs with one integration source owner.
2. Reconcile reviewed source seals before regenerating artifacts. Finish
   `tests/maintenance/generate_interface_depth_inventory.py`, then generate
   `tests/maintenance/branch_coverage_audit.py`; use their `--check` modes to prove
   the final artifacts are current. Preserve all native IDs, owners and evidence.
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
