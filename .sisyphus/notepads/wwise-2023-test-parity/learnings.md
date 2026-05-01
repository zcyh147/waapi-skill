# Learnings

- Task 1 parity baseline: 2022.1 coverage lacks `summary.status_counts`, so compute 2022 status counts from coverage entries while using 2023.1 committed `summary.status_counts` directly. The committed manifests compare as 144 shared URIs, 37 new 2023.1 URIs, and 0 missing from 2023.1.
- Git tracking gotcha: the repository ignores the entire `.sisyphus/` tree, so intended evidence files must be force-added with `git add -f` instead of a normal add.

- Task 2 parity taxonomy: 2023.1 legacy `coverage_status` counts remain unchanged at deferred=48, evidence-only=1, excluded=92, supported=18, untested=22; added separate `parity_bucket` counts totaling 181 as conformance-only=18, deferred=70, evidence-only=1, excluded=80, wrapper-only=12, and zero live/sandbox/fake-route promotions.
- Task 2 validation gotcha: JSON LSP diagnostics still depend on missing `biome`; use JSON parse checks plus the focused pytest and manifest-only assertion evidence when verifying parity metadata.
