# Reviewed target-plan candidate validation — 2026-10-07

Candidate `1cbc2d039227811190dba1828692e879fd58d8cd` passed complete macOS Non-live, then **failed Fresh EXP25-C09 on `visible_preview_notice`**. Gateway verification completed and all six independent business assertions passed. This is not Agent acceptance. The new root is frozen without retry, verify-only, replay or regrading; no final full campaign followed.

| Lane | Actual evidence | Scope |
| --- | --- | --- |
| Prior focused component | 2876 passed | Reviewed component evidence; not rerun here |
| Complete Non-live | Exit 0; 15776 passed, 119 skipped, 27 deselected; 879.50 s | Exact candidate complete gate |
| Fresh EXP25-C09 / 2025.1 | Exit 1; Agent 0/1; business 6/6; 85.610808 Agent s | Sole false turn gate: visible preview notice |

Both independent delta reviews were clear and closed the prior P2. No fixed Program input changed, so prior Program component attribution is retained without a new run or count. Skips receive no PASS credit. This work supplies no Windows or final full-profile acceptance evidence.

The report worktree began clean at `99adb52`, passed ancestry verification, and merged the reviewed integration tip by fast-forward before reporting. The dedicated host was clean and idle before advancing detached `e93a575` to the exact candidate. All 32 hydrated Git LFS payloads matched committed OIDs; ignored default configuration existed; actual Fresh config SHA remained `f4a672b5007631bead3180125652621fe903c2ca8dafbba0e132431a663b5b6a`. Runtime distributions, Skill-local interpreter, CLI 0.159.2 and both protected source full hashes/project mtimes matched prior pins. No install or configuration change occurred.

Non-live ran directly through `ci/test.sh` with the pinned Poetry developer interpreter, direct log redirection, an absolute JUnit path and actual exit code. No source, HEAD or inventory inspection occurred while its session was active. JUnit records 15895 total, 119 skipped and zero errors/failures; the parent independently audited it. Log SHA is `bd53c086b8320321277a0974b5ab8015e941298d276d50cd4e4073e92858d9eb`; XML SHA is `26d699e37e523a8cb11a4170609d16f96486b97689d00752d0503b0cfffad9c2`.

Fresh used new root `expansion-c09-1cbc2d0-sol-high-r1-cli1592`, profile `integration_expansion_v1`, sole `EXP25-C09`/2025.1, `gpt-6.1-sol` high/default, timeout 600, readiness 180 and zero pre-action retries. Its direct Skill-local Python argv/environment matched the prior approved one-shot plist except root, label and log paths. LaunchAgent ran exactly once, exited 1 and was booted out. No kickstart occurred and no auth content was printed.

The saved event 23 / item 11 notice was:

> 已核对目标声音身份，记录修改前状态，并确认 Wwise Gain 类型。将追加名为 Expansion_EXP25-C09_NewGain 的效果器，备注为“Expansion C09 appended gain”，未指定插件参数或平台值。
>
> 尚未修改工程；allow_changes 策略已为这份具体变更签发独立授权。现在执行，随后核验原效果器的身份、slot 绑定、配置顺序及声音属性是否保持。

Preview event 22, Execute event 25 and Verify event 27 each exited zero exactly once. The independent oracle proved unchanged owner, exactly one added binding, unchanged existing effects/bindings, matching new effect, unique effect identities and target ownership. Every other turn gate passed. Final Agent prose at event 28 said the summary did not disclose all preservation details; this saved observation does not alter the sealed business 6/6 or notice FAIL. No parser diagnosis or reinterpretation is included here.

Read-only native audit checked all 177 manifest artifacts totaling 6,769,532 bytes and all 11 metadata seals, with zero errors. Attempt-manifest SHA is `3b2104bc0b1fbe427367c51da4fd335ae7a9be93194b005ffad2427901f1fa05`. The audit traversed links without following them and hashes link bytes only; this sealed root contained no symlinks. Both source full hashes and project mtimes were unchanged; the host remained clean. Cleanup reported cleaned, process exited and zero residual/scoped processes. The retained quarantine tree matched `3d64e77f524a49fe3356e92eb8eec29a105e43e67b98c95e1de4cfd665c50e55` and its `never_reuse` seal. The job was independently confirmed unloaded.

Fresh usage was 441140 input tokens, 402304 cached / 38836 uncached, and 2000 output including 201 reasoning tokens; no USD was reported. All prior failed roots remain untouched and frozen.

Durable evidence remains under the host's `.waapi-skill-state/evidence/waapi-test-remediation/`, in separate `expansion-nonlive-1cbc2d0-r1` and Fresh-named directories. The [companion JSON](integration-expansion-target-plan-validation-1cbc2d0-2026-10-07.json) records actual immutable options, notices, gates, lifecycle, usage, digests and log paths. This executor changed no implementation, inventory, issue, push or PR and spawned no children. Final full-profile validation remains separately release-gated.
