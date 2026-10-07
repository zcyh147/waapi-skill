# Reviewed operation-noun candidate validation — 2026-10-07

Candidate `e93a57599387b3241170f79b21682c0230463ee3` passed complete macOS Non-live, then **failed Fresh EXP25-C09 on `visible_preview_notice`**. All six independent business assertions passed and Gateway verification completed. This is not Agent acceptance. The new root is permanently frozen without retry, verify-only, replay or regrading; no final full campaign followed.

| Lane | Actual evidence | Scope |
| --- | --- | --- |
| Prior focused component | 2770 passed, 4.64 s | Existing reviewed evidence; not rerun here |
| Complete Non-live | Exit 0; 15670 passed, 119 skipped, 27 deselected; 866.66 s | Exact candidate complete gate |
| Fresh EXP25-C09 / 2025.1 | Exit 1; Agent 0/1; business 6/6; 83.26148033305071 agent s | Sole false turn gate: visible preview notice |

Both independent review axes were clear before validation: Standards found zero new findings; Spec closed the negative-path P2 and found no new issue. The prior focused attribution retains 2742 controls plus 28 new controls. Program inputs remain unchanged and prior component attribution is preserved; no new Program run or count is claimed. Skips receive no PASS credit, and this work supplies no native-Windows evidence.

The report branch `codex/expansion-noun-validation` began at the exact integration tip; ancestry passed and its integration merge before reporting was already up to date. The dedicated host was clean before switching detached `700914d` to `e93a575`. No owned tests, Fresh or real Wwise process overlapped. All 32 hydrated Git LFS payloads matched committed OIDs, the ignored default config existed, and the pinned Poetry developer interpreter was available. Existing ignored evidence and failed sandboxes were preserved.

Non-live ran directly through `ci/test.sh --mode nonlive -- -q -ra` with `WAAPI_TEST_PYTHON=/Users/xiye/Library/Caches/pypoetry/virtualenvs/non-package-mode-nsP1lGog-py3.11/bin/python`, an absolute JUnit path, direct log redirection and the actual exit code. No source, HEAD or inventory inspection occurred while tests were active. The parent independently confirmed JUnit's 15789 total, 119 skipped and zero failures/errors. Log SHA: `c9b0f90b0ebfde52f3cd9a4610d81d421486fb50327dddf7a7a403f70aedd1e3`; XML SHA: `453a091fcef4ad87e273a79a8c43e3b8736e2c0e0ecf515933df3db2e4fd2542`.

Two optional local preflight helpers initially failed: one omitted the Skill import path, and one omitted the explicit default config input. They neither created a campaign root nor started an Agent turn. Correct repository-relative config resolution, all source full hashes/project mtimes, clean candidate, zero owned processes, dependencies, Skill-local interpreter, runtime distributions, CLI 0.159.2 and runtime config pins passed before bootstrap. No environment installation or source repair was needed.

Fresh used new root `expansion-c09-e93a575-sol-high-r1-cli1592`, existing `integration_expansion_v1`, sole `EXP25-C09`/2025.1, `gpt-6.1-sol`, high reasoning/default tier, timeout 600, readiness 180 and zero pre-action retries. Its direct Python argv and environment matched the prior approved plist except the new root/label/log paths. The one-shot LaunchAgent bootstrapped once in `gui/501`, ran once, exited 1 and was booted out. No kickstart occurred. Auth contents were never printed. The pinned actual Fresh config remained `.waapi-skill-state/runtime/expansion-frozen-live-environment.json`, rather than the portable default path.

The saved event 23 notice was:

> 目标已核对，追加方案已按 allow_changes 策略取得独立持久授权，目前尚未修改工程。即将追加 Wwise Gain 效果器 Expansion_EXP25-C09_NewGain，备注为“Expansion C09 appended gain”，不另设插件参数或平台值；执行后将核验原有效果器的身份、slot 绑定和顺序，以及声音属性的保持情况。

One immutable Preview, Execute and Verify each exited zero. The independent oracle established unchanged owner, exactly one added binding, unchanged existing effects/bindings, matching new effect, unique effect identities and target ownership. All other turn gates passed. Final Agent prose said preservation could not be confirmed because it lacked a detailed comparison; this saved observation does not alter the sealed business 6/6 or notice FAIL. No new implementation diagnosis or reinterpretation was performed.

Native audit independently checked 177 manifest artifacts totaling 6,769,405 bytes and all 11 metadata seals, with zero audit errors. Attempt-manifest SHA: `1e1a0153c7c0b2ed6129ba63d766b2ab69296f8ee5ffa0c560f54426fc8bc5b5`. Protected source full hashes and project mtimes matched preflight; the host remained clean at exact candidate. Cleanup reported cleaned, process exited and zero residual/scoped processes. The retained quarantine tree independently matched SHA `93305ec82db2ae96e542519258188636670c9ce04299cd9e5c2d6326b84de3c0` and its `never_reuse` seal. The job was confirmed unloaded.

Fresh usage was 441073 input tokens, 394752 cached and 46321 uncached; 1972 output including 185 reasoning tokens; no reported USD. The historical `700914d` root remains its original frozen notice FAIL with six business assertions true. Neither it nor any other prior failed root was replayed, regraded, resumed, deleted or reused.

Durable native evidence remains on `/Users/xiye/.codex/worktrees/expansion-frozen-campaign/waapi-skills/.waapi-skill-state/evidence/waapi-test-remediation/`, under separate `expansion-nonlive-e93a575-r1` and Fresh-named directories. The companion JSON records exact argv, preflight, notices, gates, lifecycle, usage, artifact digests and terminal audit. This executor changed no implementation, test inventory, issue, push or PR. No children were spawned; any future delegation must explicitly use `fork_turns="none"` and propagate that rule.
