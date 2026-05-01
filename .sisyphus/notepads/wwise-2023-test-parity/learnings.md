# Learnings

- Task 1 parity baseline: 2022.1 coverage lacks `summary.status_counts`, so compute 2022 status counts from coverage entries while using 2023.1 committed `summary.status_counts` directly. The committed manifests compare as 144 shared URIs, 37 new 2023.1 URIs, and 0 missing from 2023.1.
- Git tracking gotcha: the repository ignores the entire `.sisyphus/` tree, so intended evidence files must be force-added with `git add -f` instead of a normal add.

- Task 2 parity taxonomy: 2023.1 legacy `coverage_status` counts remain unchanged at deferred=48, evidence-only=1, excluded=92, supported=18, untested=22; added separate `parity_bucket` counts totaling 181 as conformance-only=18, deferred=70, evidence-only=1, excluded=80, wrapper-only=12, and zero live/sandbox/fake-route promotions.
- Task 2 validation gotcha: JSON LSP diagnostics still depend on missing `biome`; use JSON parse checks plus the focused pytest and manifest-only assertion evidence when verifying parity metadata.

- Task 3 live read-only parity: `ak.wwise.core.object.get` is the only live-tested 2023.1 URI after read-only WAQL expansion; eight sandboxed live cases write per-case JSON under `.sisyphus/evidence/wwise-2023-test-parity/live-read-only/` and keep source hash/mtime unchanged.
- Task 3 validation gotcha: direct Glob did not list hidden `.sisyphus` evidence files, but `Read` on `.sisyphus/evidence/wwise-2023-test-parity/live-read-only/` confirmed all eight JSON files exist after the exact live command.

- Task 3 live read-only promotion: the exact 2023.1 sandbox command passed after moving the fake-client mutation guard to `tests/unit/test_2023_waql_live_matrix.py`; final live command result was 10 passed, and the focused unit suite for 2023 WAQL/coverage was 16 passed.
- Task 3 coverage promotion rule: only `ak.wwise.core.object.get` moved to `live-tested`; coverage summaries/policy now have live-tested=1 and evidence-only=0 for the 2023.1 parity bucket/status counts.
- Task 3 test-quality gotcha: guard tests placed under `tests/live/` are skipped by default because `tests/conftest.py` treats the live path as a live keyword; keep helper-only guard tests in `tests/unit/`.
- Task 3 WAQL assertion gotcha: `allow_empty` matrix cases with identity expectations must skip identity checks when rows are empty; identity applies only to returned rows.
