# Reviewed candidate validation, 2026-10-07

The complete macOS Non-live gate at `700914d86b10dc1c586762fb3a617a0fd4e9ab2a` failed with exit 1: **20 failed, 15531 passed, 119 skipped, 27 deselected, 6 errors in 886.28 seconds**. Fresh EXP25-C09 was not launched. The intended fresh root remains absent. No retry, fixture hydration, configuration edit, repair, replay, verify-only or final full campaign followed this result.

The report branch `codex/expansion-reviewed-validation` was created from the exact integration tip; `git merge-base --is-ancestor` succeeded. Before publishing, `git merge --ff-only codex/waapi-expansion-integration` reported already up to date. The dedicated campaign host was tracked clean before switching detached from `0c2e75e` to `700914d`; ignored runtime and historical evidence were preserved. No owned test, Fresh or Wwise process overlapped the run. Candidate/source inspection waited for actual pytest exit and zero owned processes.

The direct command used the pinned Poetry developer interpreter through `WAAPI_TEST_PYTHON` and `ci/test.sh --mode nonlive -- -q -ra`, with the absolute XML path in the JSON report. Output was redirected directly into the durable host evidence directory, and the invoking shell saved and returned the actual exit code. It was not piped through tee.

The 26 unsuccessful cases separate into these exact groups:

- Ten failures and six setup errors in public integration loaders: component-02 invalid, caused by the 2022.1 manifest full-tree hash drifting.
- One V2 baseline-preflight failure: the same 2022.1 manifest hash drift.
- Three music-fixture failures: donor WAV hash mismatch, including a test that could not reach its injected failure.
- Three campaign-parser failures: `SystemExit: 2` because the dedicated host lacks `tests/fixtures/local/live-environment.json`.
- Three org-fixture manifest failures: expected 12404 payload bytes, observed a 130-byte Git LFS pointer.

These are observed prerequisite failures, not completed acceptance. The report does not infer that all failures would disappear after hydration or configuration restoration. The machine-readable companion retains all failing case names and terminal messages.

Durable evidence remains under `/Users/xiye/.codex/worktrees/expansion-frozen-campaign/waapi-skills/.waapi-skill-state/evidence/waapi-test-remediation/expansion-nonlive-700914d-r1/`. SHA-256: log `0582a4c5fa2d419c5efb8f6b6c417ff0078d62e28a4c6b5ba70ff41a743861c0`; XML `5a4e7bc6e0608270b9c7008fdf8ebdf1fe6d76f103c0cab2e84f906a2781fa34`; terminal audit `25f01381c57660084c196f4483dcf74d3b8e5718b39d4e42f8dcd6f9d1b2efaa`. The audit records clean detached HEAD, zero scoped processes, and exact equality to the prior protected source full hashes and project mtimes for both Wwise versions. The packaged Skill digest remains `3049959ab97ea387bfaaabc3b0316ff332a400e0f921c540e7337aadd5217422`.

The completed focused component remains 2657 passed in 4.70 seconds (2566 retained plus 91 new controls), from the existing repair evidence. It was not rerun here. No new Program gate was run or claimed; prior unchanged Program component attribution is preserved.

Historical root `expansion-c09-0c2e75e-sol-high-r2-clean-cli1592` remains FAIL on `visible_preview_notice`, despite six of six business assertions and one verified Preview/Execute/Verify sequence. Its original agent time was 96.78919045906514 seconds; usage was 441330 input tokens (402432 cached, 38898 uncached), 2053 output tokens including 304 reasoning tokens, no reported USD. This remains historical business success with notice failure, not repaired-candidate Agent PASS.

A post-gate read-only capability check found no existing priority/order CLI option. The expansion loader creates version-major CASE_IDS order and then filters selectors, so supplying C09 first in repeated `--case-id` does not put it first. A targeted root cannot later expand its immutable selection into the full root. No alternative launch or harness/suite modification was attempted.

Coordination checkpoint: all new subagents must explicitly use `fork_turns="none"`, with only necessary objective, constraints, acceptance, path pointers and essential unrecorded decisions; this rule propagates recursively. No goal metadata edit is claimed. The coordinator reports 137/138/139/140/142/143 closed on existing component proof and 156 closed with an explicit unsupported complete-tool-inventory telemetry boundary; 147/122/108 remain open. No issues, push or PR were changed by this executor.
