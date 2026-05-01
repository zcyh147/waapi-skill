# Learnings

- Task 1 parity baseline: 2022.1 coverage lacks `summary.status_counts`, so compute 2022 status counts from coverage entries while using 2023.1 committed `summary.status_counts` directly. The committed manifests compare as 144 shared URIs, 37 new 2023.1 URIs, and 0 missing from 2023.1.
- Git tracking gotcha: the repository ignores the entire `.sisyphus/` tree, so intended evidence files must be force-added with `git add -f` instead of a normal add.
