# Reviewed purpose-composition candidate validation — 2026-10-07

Candidate `d8ef3bd5d51e80eded1ba6bb1c37d77f8645c6eb` passed complete macOS Non-live, then **failed Fresh EXP25-C09 on `visible_preview_notice`**. Gateway verification and all six independent business assertions passed. This is not Agent acceptance. The failed root is frozen without retry, resume, replay, regrading or verify-only. The final 13-unit campaign remains unreleased.

| Lane | Actual result | Scope |
| --- | --- | --- |
| Prior focused component | 3093 passed | Reviewed component evidence; not rerun here |
| Complete Non-live | Exit 0; 15993 passed, 119 skipped, 27 deselected; 844.02 s | Exact candidate complete gate |
| Fresh EXP25-C09 / 2025.1 | Exit 1; Agent 0/1; business 6/6; 117.067253 Agent s | Sole false gate: visible preview notice |

Both reviews were clear. Packaged Skill and fixed Program inputs were unchanged, so prior Program component applicability is retained without a new run or passing count. Skips grant no PASS credit. This report grants no Windows or final full-profile acceptance.

The report worktree confirmed candidate ancestry and created `codex/expansion-purpose-validation`. It merged the integration tip before reporting (already up to date at exact `d8ef3bd`). The durable host was clean and idle before advancing detached `0b6af50` to this candidate. All 32 hydrated LFS payloads matched committed OIDs. The ignored default live config existed; actual Fresh config SHA remained `f4a672b5007631bead3180125652621fe903c2ca8dafbba0e132431a663b5b6a`. CLI 0.159.2 and SHA `16593cc2f422d5f398a8e40f550ebbaf1245392528957be342c295920a300704`, actual installed minimal runtime, unchanged Skill tree, protected source full hashes and project mtimes matched prior pins. Readiness mistakenly imported absent developer-only `jsonschema`; that extra import was removed, without installation, runtime update or config change.

Non-live ran once through `ci/test.sh` with the pinned Poetry developer interpreter, direct log redirection, absolute JUnit path and actual exit code, session `89274`. No source, HEAD or inventory inspection occurred while it was active. JUnit records 16112 total, 119 skipped and zero failures/errors; the parent independently matched the result and hashes. Log SHA is `b363e435a962575881169c1c6b44909a43e3468c285c0e37cbdce29e08ab8c45`; XML SHA is `22ae105d4d56decee5e71cb3da23e4badf1326ab8a0f493cd7e95e50368e5275`. Post-run readiness again passed.

Fresh used new root `expansion-c09-d8ef3bd-sol-high-r1-cli1592`, profile `integration_expansion_v1`, sole `EXP25-C09`/2025.1, `gpt-6.1-sol` high/default, timeout 600, readiness 180 and zero pre-action retries. Direct Skill-local Python argv/environment matched the prior approved one-shot LaunchAgent recipe except root, label and log paths. The job ran exactly once and exited 1. It was booted out; subsequent lookup returned 113 and service absent. No kickstart or auth-content read occurred. The inactive evidence plist is retained.

The saved notice at event 23 / item 11 was:

> 已核对目标声音，解析出的 GUID 与你提供的一致，并已记录修改前状态。将追加 Wwise Gain 效果器 `Expansion_EXP25-C09_NewGain`，备注为“Expansion C09 appended gain”，不另设插件参数或平台值；执行后会对照原状态核验现有效果器的身份、绑定和顺序。
>
> 目前尚未修改工程。此次具体变更已取得 `allow_changes` 策略下的独立持久授权，现在执行并核验。

Preview event 22 / item 10, Execute event 25 / item 12 and Verify event 27 / item 13 each exited zero exactly once. The independent oracle proved unchanged owner, exactly one added binding, unchanged existing effects/bindings, matching new effect, unique effect identities and target ownership. Every other turn gate passed. Final prose at event 28 / item 14 said the six-check summary lacked individual preservation results for the two original effects and sound attributes. These saved facts do not reinterpret the sealed business 6/6 or notice FAIL.

Read-only native audit matched all 177 manifest artifacts totaling 6770553 bytes and all 11 metadata seals, with zero audit errors. Attempt-manifest SHA is `97544b3e1eb6746dc6676b113667ee31502ed09a9e7e22c6b3a5471fd3b9e93c`. Link inspection used `os.walk(followlinks=False)` and hashes link bytes only; the sealed root contained no symlinks. Both source full hashes and project mtimes remained unchanged. The host stayed clean, cleanup reported cleaned/process exited, and residual/scoped processes were empty. The retained quarantine tree matched its seal with `never_reuse=true`. All older FAIL roots remain preserved.

Fresh usage was 441951 input tokens (390912 cached, 51039 uncached) and 2118 output including 276 reasoning tokens; no USD was reported. Raw evidence remains in separate Non-live and Fresh folders under the durable host’s `.waapi-skill-state/evidence/waapi-test-remediation/`. The [companion JSON](integration-expansion-purpose-validation-d8ef3bd-2026-10-07.json) records pins, options, gates, notices, lifecycle, source guards and evidence digests. No implementation, inventory, issue, push or PR changed; no children were spawned and no durable host or evidence was deleted.
