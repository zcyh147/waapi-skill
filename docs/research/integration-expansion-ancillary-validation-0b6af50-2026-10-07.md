# Reviewed ancillary candidate validation — 2026-10-07

Candidate `0b6af50d10cf2fe85f2fbdde5407c936fac69fd0` passed complete macOS Non-live, then **failed Fresh EXP25-C09 on `visible_preview_notice`**. Gateway verification and all six independent business assertions passed. This is not Agent acceptance. The sealed failed root remains frozen without retry, resume, replay, regrading or verify-only. The final 13-unit campaign was not released or run.

| Lane | Actual result | Scope |
| --- | --- | --- |
| Prior focused component | 3023 passed | Reviewed component evidence; not rerun here |
| Complete Non-live | Exit 0; 15923 passed, 119 skipped, 27 deselected; 847.23 s | Exact candidate complete gate |
| Fresh EXP25-C09 / 2025.1 | Exit 1; Agent 0/1; business 6/6; 93.864315 Agent s | Sole false gate: visible preview notice |

Both final reviews were clear. Fixed Program inputs were unchanged, so prior Program component attribution is retained without a new run or passing count. Skips grant no PASS credit. This report grants no Windows or final full-profile acceptance.

The report worktree began clean at the integration candidate, confirmed ancestry and created `codex/expansion-ancillary-validation`; the integration tip was merged before reporting. The durable host was clean and idle before advancing detached `1cbc2d0` to the exact candidate. All 32 hydrated LFS payloads matched their committed OIDs. The ignored default live config existed; actual Fresh config SHA remained `f4a672b5007631bead3180125652621fe903c2ca8dafbba0e132431a663b5b6a`. CLI 0.159.2, its `16593cc2…` digest, Skill-local runtime, unchanged Skill tree, protected source full hashes and project mtimes matched prior pins. Readiness initially queried two absent developer-only distributions; the audit was corrected to record the actual installed minimal runtime without installing or changing configuration.

Non-live ran once through `ci/test.sh` with the pinned Poetry developer interpreter, direct log redirection, absolute JUnit path and actual exit code, session `51410`. No source, HEAD or inventory inspection occurred while the gate was active. JUnit records 16042 total, 119 skipped and zero failures/errors; the parent independently confirmed it. Log SHA is `45cc1e92e73e8e3b0c4cf7c710dfc630c522011ff460efca4e93535baaed67a3`; XML SHA is `d9f1193f8bed56eb9cff3864d7461dd39e1105175aef587773731cd302b2d268`.

Fresh used new root `expansion-c09-0b6af50-sol-high-r1-cli1592`, profile `integration_expansion_v1`, sole `EXP25-C09`/2025.1, `gpt-6.1-sol` high/default, timeout 600, readiness 180 and zero pre-action retries. Direct Skill-local Python argv/environment matched the prior approved one-shot LaunchAgent recipe except root, label and log paths. The job ran exactly once and exited 1; it was booted out, with subsequent service lookup returning 113 and service absent. No kickstart or auth-content read occurred.

The saved event 23 / item 11 notice was:

> 已核对目标声音身份，并记录修改前状态用于保持性核验。将追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”，不另设插件参数或平台值。
>
> 已取得 allow_changes 策略的独立授权，当前尚未修改工程。现在执行追加，随后核验现有两个效果器的身份、slot 绑定、配置及顺序，以及声音的音量、备注和父级是否保持。

Preview event 22 / item 10, Execute event 25 / item 12 and Verify event 27 / item 13 each exited zero exactly once. The independent oracle proved unchanged owner, exactly one added binding, unchanged existing effects/bindings, matching new effect, unique effect identities and target ownership. Every other turn gate passed. Final Agent prose at event 28 / item 14 said the six-check summary lacked individual comparisons for the original effects and sound attributes. These saved facts do not reinterpret the sealed business 6/6 or notice FAIL.

Read-only native audit checked all 177 manifest artifacts totaling 6773521 bytes and all 11 metadata seals, with zero audit errors. Attempt-manifest SHA is `767f1bed0e7abf873eb194fd58e8f4223ffc24ec76fb4cb872876b538fb5aaec`. Link traversal used `followlinks=False` and would hash link bytes only; the sealed root contained no symlinks. Both source full hashes and project mtimes remained unchanged; the host stayed clean. Cleanup reported cleaned and process exited, with zero residual/scoped processes. The retained quarantine tree matched its seal and `never_reuse=true`. All older FAIL roots remain preserved.

Fresh usage was 442545 input tokens, 403456 cached / 39089 uncached, and 2150 output including 225 reasoning tokens; no USD was reported. Durable evidence remains in separate Non-live and Fresh directories under the host's `.waapi-skill-state/evidence/waapi-test-remediation/`. The [companion JSON](integration-expansion-ancillary-validation-0b6af50-2026-10-07.json) records options, notices, gates, lifecycle, pins and artifact digests. This executor changed no implementation, inventory, issue, push or PR and spawned no children.
