# GUID comparison candidate validation — 2026-10-07

Candidate `67279dbf6baec55ddec90448419587055f49ff57` passed complete macOS Non-live, then **failed Fresh EXP25-C09 on `visible_preview_notice`**. Gateway verification and all six independent business assertions passed. Agent acceptance remains failed. The new root is frozen without retry, resume, replay, regrading or verify-only; the final 13-unit campaign remains unreleased.

| Lane | Actual result | Scope |
| --- | --- | --- |
| Prior focused component | 3766 passed | Reviewed component evidence; not rerun here |
| Complete Non-live | Exit 0; 16609 passed, 119 skipped, 27 deselected; 865.80 s | Exact candidate complete gate |
| Fresh EXP25-C09 / 2025.1 | Exit 1; Agent 0/1; business 6/6; 92.331799 Agent s | Sole false gate: visible preview notice |

Both independent reviews were clear. Packaged Skill and fixed Program inputs were unchanged from `d8ef3bd`; the descendant delta is documentation, semantic fixtures, harness and tests. Prior Program applicability is retained without a new Program run or passing count. Skips grant no PASS credit. This report grants no Windows or full-profile acceptance.

The report checkout created `codex/expansion-guid-validation` at exact `67279db` and merged the integration tip before reporting (already up to date). The durable execution host was clean and idle before its detached checkout advanced from exact `d8ef3bd` to `67279db`; existing ignored runtimes, config, media, campaigns and quarantines were preserved. All 32 hydrated LFS payloads matched committed OIDs. Both protected source full hashes and project mtimes matched prior pins. Explicit Fresh config SHA remained `f4a672b5007631bead3180125652621fe903c2ca8dafbba0e132431a663b5b6a`; the ignored default config was not selected. CLI 0.159.2 SHA remained `16593cc2f422d5f398a8e40f550ebbaf1245392528957be342c295920a300704`. Minimal installed runtime versions and the stable Skill-local interpreter matched, with no dependency installation or developer-only jsonschema import.

Non-live ran exactly once through `ci/test.sh`, pinned Poetry developer interpreter, direct log redirection and absolute JUnit path, in PTY session `83978` (driver PID `71821`, pytest PID `71825`). The same handle was polled to terminal exit 0. No source, HEAD or inventory inspection occurred during the gate. JUnit records 16728 total, 119 skipped and zero errors/failures. Both owned PIDs exited; post-run readiness passed. Log SHA is `52d50c76bcb6f605f510cadaace750c06098d77c8491ae6fc4d6c2317f9d464d`; XML SHA is `08ed3f6ecfb768056c835387d11cc566e88b627277e8978d79c5f9b9751a8098`. The parent independently matched the terminal facts and hashes in `parent-gate-audit.json`.

Fresh used root `expansion-c09-67279db-sol-high-r1-cli1592` with profile `integration_expansion_v1`, sole `EXP25-C09`/2025.1, `gpt-6.1-sol` high/default, readiness 180, Agent timeout 600 and zero pre-action retries. Direct Skill-local Python argv and environment matched the precedent except new root, label and log paths. One-shot LaunchAgent `gui/501/local.codex.waapi.expansion-c09-67279db-sol-high-r1-cli1592` ran exactly once as PID `90527`, then exited 1. It was booted out; subsequent lookup returned 113. No kickstart, restart, auth-content read or default-config substitution occurred. The inactive evidence plist is retained.

The saved notice at event 23 / item 11 was:

> 已核对目标为指定声音，并记录修改前状态。本次将追加 Wwise Gain 效果器 `Expansion_EXP25-C09_NewGain`，备注为“Expansion C09 appended gain”；核验会检查原有效果器的身份、slot 绑定和顺序，以及声音属性是否保持。
>
> 当前尚未修改项目。此次变更已获得 `allow_changes` 策略的独立授权，现在执行追加并核验。

It contains no explicit GUID comparison. Preview event 22 / item 10, Execute event 25 / item 12 and Verify event 27 / item 13 each exited zero exactly once. All other turn gates passed. The independent oracle proved unchanged owner, exactly one added binding, unchanged existing effects/bindings, matching new effect, unique effect identities and target ownership. Final prose at event 28 / item 14 said the six-check summary lacked individual preservation comparisons for the original effects and sound attributes. These saved facts do not reinterpret the sealed notice FAIL or business 6/6.

Read-only native audit matched all 177 manifest artifacts totaling 6769542 bytes and all 11 metadata seals, with zero errors. Attempt-manifest SHA is `d4f9fb5bfbb33c7121a5867605b6c53f82904327a8a826ad94d679f1b2db4740`. Link inspection used `os.walk(followlinks=False)` and hashes `os.readlink` bytes only; the sealed root contained no symlinks. Both source full hashes/mtimes and candidate input hashes remained unchanged, the host stayed clean, cleanup reported process exited/cleaned, and scoped residual processes were empty. The retained quarantine tree matched its seal `605a23116c29a5cf5a7c5cf0b76d040d723467e59b41023e9d2ab8d8989d3962` with `never_reuse=true`. All historical failed roots remain preserved.

The [companion JSON](integration-expansion-guid-validation-67279db-2026-10-07.json) records exact launch/options, readiness, gates, saved notices, usage, lifecycle, quarantine and evidence digests. Raw Non-live and Fresh evidence remains in separate folders under the durable host's `.waapi-skill-state/evidence/waapi-test-remediation/`. This report changes no runtime code, README/inventory count, issue, push or PR; no child agent was spawned and no evidence was deleted.
