# Implementation batches and checks

Use this sequence for the current coverage implementation. Historical acceptance
belongs in [the test inventory](../../../tests/TEST_INVENTORY.md); current Fresh
scheduling and failure classification belong in [business acceptance](../../../tests/semantic/TEST_ACCEPTANCE.md).

1. Freeze one bounded batch of explicitly selected immutable worker refs. Workers
   run their relevant focused cases; keep later successors separate. Merge only
   the selected refs with one integration source owner.
2. Reconcile reviewed source seals before regenerating artifacts. Finish
   `tests/maintenance/generate_interface_depth_inventory.py`, then generate
   `tests/maintenance/branch_coverage_audit.py`; use their `--check` modes to prove
   the final artifacts are current. Preserve all native IDs, owners and evidence.
3. Freeze the merged, reconciled candidate for the central batch/PR preflight:
   `poetry run python ci/preflight.py`. It runs existing roster/schema seals,
   the complete fake public-route matrix and actual Tone terminal-output controls
   through `ci/test_driver.py`. It takes no selection overrides and launches no
   Wwise or Codex. The PR workflow uses the same command with Python 3.11 and
   locked Poetry dependencies. This is a cheap development guard, not full
   Program acceptance or a requirement for every small worker handoff.
4. Deduplicate the affected selection and run one proportional combined focus
   for behavior beyond the preflight. Keep each original verdict bound to its
   tested candidate; an unchanged worker check need not be repeated wholesale.
5. Run required Program and Non-live gates at the necessary settled milestone.
   Keep source unchanged while tests run and wait on the same live process
   handle; report terminal results, new failures or decisions. Inspect source
   only after the owned group ends. Record exact results and unresolved work;
   preserve failed evidence.

The workflow has read-only permissions, cancels superseded PR runs and uses only
the official [checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1)
and [setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0)
actions pinned to their full release commit IDs. Local preflight success does not
prove hosted CI, Windows or native-Wwise acceptance.
