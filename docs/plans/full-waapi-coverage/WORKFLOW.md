# Implementation batches and checks

Use this sequence for the current coverage implementation. Historical acceptance
belongs in [the test inventory](../../../tests/TEST_INVENTORY.md); current Fresh
scheduling and failure classification belong in [business acceptance](../../../tests/semantic/TEST_ACCEPTANCE.md).

1. Agree on one bounded batch and explicit immutable worker refs. Keep successor
   work separate until that batch is integrated. One agent owns integration
   source; keep it unchanged while its tests run.
2. Run the directly affected tests first. Before handoff, run
   `poetry run python ci/preflight.py`: existing roster/schema seals, the complete
   fake public-route matrix, and actual Tone terminal-output controls through
   `ci/test_driver.py`. It takes no selection overrides and launches no Wwise or
   Codex. The PR workflow runs the same command with Python 3.11 and locked Poetry
   dependencies. This is a cheap development guard, not full Program acceptance.
3. Reconcile reviewed source seals before regenerating artifacts. Finish
   `tests/maintenance/generate_interface_depth_inventory.py`, then generate
   `tests/maintenance/branch_coverage_audit.py`; use their `--check` modes to prove
   the final artifacts are current. Preserve all native IDs, owners and evidence.
4. Merge only the agreed refs, deduplicate the real test selection, then run one
   proportional combined focus. Keep each original verdict bound to its tested
   candidate; an unchanged worker check need not be repeated wholesale.
5. Once the batch is settled, freeze the final candidate for required Program and
   Non-live gates. Wait on the same live process handle; report terminal results,
   new failures or decisions. Inspect source only after the owned group ends.
   Record exact results and unresolved work; preserve failed evidence.

The workflow has read-only permissions, cancels superseded PR runs and uses only
the official [checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1)
and [setup-python v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0)
actions pinned to their full release commit IDs. Local preflight success does not
prove hosted CI, Windows or native-Wwise acceptance.
