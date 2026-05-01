
- Background exploration unexpectedly modified `references/wwise-version-upgrade-2023-first.md`; I restored it to HEAD before implementation.

- No new blockers for the 2025.1 version/live-environment contract task; no live or destructive Wwise calls were needed.

- Resolved during Task 2: the first 2025.1 fixture inventory run failed because the destructive guard test used a temporary console without patching the exact 2025.1 console contract; patched the test contract and reran targeted/regression pytest successfully.

- Resolved review blocker: code review flagged the destructive guard test as non-hermetic when the real 2025.1 SampleProject is absent. Fixed with a `tmp_path` installed project and reran `test_2025_1_fixture_inventory.py` plus 2023/2024 fixture regressions successfully.

- Resolved during Task 3: the first 2025.1 WwiseConsole launch did not expose WAAPI before the default 60s readiness timeout; reran through the same lifecycle with `WWISE_READINESS_TIMEOUT=180` and captured successful live reflection evidence.
- JSON LSP diagnostics were unavailable because the configured `biome` server is not installed; generated JSON was validated with `json.loads`, Python test diagnostics were clean, and targeted/regression pytest passed.

- Resolved Task 3 full-suite regression: `test_no_2025_resource_payloads_were_introduced` predated planned explicit `resources/manifest/2025.1/` payloads. Narrowed the audit to allow only `resources/manifest/2025.1` while continuing to reject bare `resources/manifest/2025/` payloads and preserving 2024 no-fallback guards; exact focused pytest and full pytest now pass.

- No new blockers in Task 4: 2025.1 isolation tests and 2024 regression audits passed, with evidence saved under `.sisyphus/evidence/task-2025-4-isolation.txt` and `.sisyphus/evidence/task-2025-4-2024-regression.txt`.

- Resolved during Task 5: a concurrent NotebookLM query failed because Chromium profile locking prevents parallel browser sessions. Sequential follow-up queries against `wwise-2025.1-docs` succeeded and supplied the missing family evidence.
- JSON LSP diagnostics were still unavailable because the configured `biome` server is not installed; `resources/semantic/2025.1/source_notes.json` was validated with `python -m json.tool` and the targeted pytest gates.
- NotebookLM did not provide exact public-library URL prefixes/page ids, only source-grounded headings and a `2025.1.7_6590` URL candidate. The discrepancy register records this caveat instead of treating URL candidates as fetched proof; the live manifest build remains `2025.1.7.9143`.

- Resolved Task 5 full-suite regression: `test_no_2025_resource_payloads_were_introduced` now allows the planned explicit 2025.1 semantic directories (`resources/semantic/2025.1` and `references/semantic/2025.1`) alongside the existing manifest allowlist, while bare `2025` and unplanned 2025 payloads remain rejected.

- Task 6 verification note: JSON LSP diagnostics still cannot run because the configured `biome` server is not installed; `python -m json.tool` validated `resources/coverage/2025.1/added-api-classification.json`, Python LSP diagnostics were clean for the new test, and focused pytest passed.

- Resolved Task 6 acceptance regression: the 2024 unplanned-payload audit needed the planned `resources/coverage/2025.1` allowlist entry, and the tracked Task 5 NotebookLM evidence had been shortened below the reference-layout contract. Restored required safe strings without recording auth artifacts.

- Task 7 verification note: JSON LSP diagnostics still cannot run because the configured `biome` server is not installed; generated JSON was validated with `python -m json.tool`, Python LSP diagnostics were clean for new tests, and focused/regression pytest passed.

- Task 7 commit note: no additional blockers were found while staging the baseline resources; the only tracked plan change was the Task 7 checkbox flip already present in the working tree.

- Task 8 verification note: LSP diagnostics were clean for the modified Python audit; `.txt` evidence files have no configured LSP server, so they were validated by content review and full pytest instead.

- Resolved during Task 9: the first exact 2025.1 WAQL live run failed because the matrix reused the 2024 Actor-Mixer Hierarchy path; updated the 2025-only matrix to the live SampleProject `Containers` root and reran the exact command successfully.
- Task 9 verification note: JSON LSP diagnostics still cannot run because the configured `biome` server is not installed; modified JSON resources were validated with `python -m json.tool`, focused 2025 pytest, exact live pytest, and the full default pytest suite.

- Task 10 verification note: no typecheck/build command is configured in `pyproject.toml`; Python LSP diagnostics were clean for the new module and test, and pytest covered the required 2025.1 destructive gates plus the 2024 safety regression.

- Resolved during Task 11: default 60s WAAPI readiness caused skipped destructive launches after copied-sandbox prep; rerunning with `WWISE_READINESS_TIMEOUT=180` produced fresh all-passed 2025.1 destructive behavior evidence (`5 passed`).
- Task 11 verification note: JSON LSP diagnostics remain unavailable for JSON resources, so changed coverage/deferred JSON was validated with `python -m json.tool`; Python LSP diagnostics were clean and focused 2025 coverage/audit pytest passed.

- Resolved during Task 12: the initial docs contract failed because an eval forbidden term and a runbook warning repeated Windows-overclaim phrases verbatim. Reworded both to reject the claim without embedding the exact forbidden language.
- Task 12 verification note: JSON resources and eval metadata were validated through Python JSON loading plus `python -m pytest tests/unit/test_2025_1_docs_contract.py tests/unit/test_eval_metadata.py -q`; Python LSP diagnostics were clean for the new test.

- Resolved during Task 12 residual cleanup: `.gitignore` evidence exceptions were scope creep because prior planned `.sisyphus/evidence` artifacts can be included with `git add -f`; reverted the ignore-policy change and kept only scoped docs/test updates.
- Resolved during Task 12 residual cleanup: full pytest exposed stale 2023 docs-contract wording that expected 2025 to remain future-only; updated the regression to assert scoped 2025.1 support instead.

- Task 13 had no new blockers; the only noteworthy outcome was that live/destructive 2025.1 selections failed closed exactly as intended when opt-in env vars were absent.
