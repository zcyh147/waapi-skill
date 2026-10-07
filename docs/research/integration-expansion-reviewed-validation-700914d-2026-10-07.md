# Reviewed candidate validation, 2026-10-07

Candidate `700914d86b10dc1c586762fb3a617a0fd4e9ab2a` passed the complete macOS Non-live rerun, then **failed the single Fresh EXP25-C09 case on `visible_preview_notice`**. The six independent business assertions passed and Gateway verification completed. This is not Agent acceptance. The Fresh root is frozen, its failed sandbox remains quarantined, and no verify-only, replay, regrading, retry or final full campaign followed.

The report branch `codex/expansion-reviewed-validation` was created from the exact integration tip; ancestry succeeded and integration-tip merge before reporting was already up to date. The campaign host was tracked clean before detaching from `0c2e75e` to `700914d`, preserving all ignored historical/runtime evidence. No source changes or overlapping test/Fresh/Wwise owner occurred. Source inspection waited for actual test exit and zero owned tests.

| Lane | Actual result | Scope |
| --- | --- | --- |
| Prior focused repair | 2657 passed, 4.70 s | Existing component evidence: 2566 retained + 91 new; not rerun here |
| Complete Non-live r1 | Exit 1; 15531 passed, 20 failed, 6 errors, 119 skipped, 27 deselected; 886.28 s | Preserved prerequisite-failure attempt |
| Recovery focused files | Exit 0; 144 passed, 3.21 s | All eight previously failing files |
| Complete Non-live r2 | Exit 0; 15557 passed, 119 skipped, 27 deselected; 899.57 s | Fresh complete gate after local preparation |
| Fresh EXP25-C09 | Exit 1; Agent 0/1; business 6/6; 95.65208924980834 agent s | Sole false gate: visible preview notice |

Both complete gates used the pinned Poetry developer interpreter through `WAAPI_TEST_PYTHON` and direct `ci/test.sh --mode nonlive -- -q -ra`, absolute JUnit paths, directly preserved logs and actual exit codes. Neither was piped through tee. No new Program run is claimed; existing unchanged Program component attribution remains intact. Skips are not passes, and there is no native-Windows credit.

The r1 unsuccessful cases were ten failures plus six setup errors cascading from public integration component-02 / 2022.1 full-tree hash drift; one V2 preflight hash failure; three pinned donor-WAV failures; three parser failures from the missing default local config; and three fixture-manifest failures observing a 130-byte LFS pointer where 12404 payload bytes were required. Their exact test names and messages remain in the companion JSON.

The coordinator authorized bounded environment recovery. Supported `git lfs checkout` hydrated 32 commit-pinned payloads from the existing local shared cache; all SHA-256 values match their LFS OIDs. No fetch/reset/clean or source-code edit was used. The missing ignored default config was copied byte-for-byte from the trusted primary config (SHA `15d0e9cc992dae7c893761c9c7e4719cdc32437bf944e94bc3a8edea30dc742d`). Its relative sources resolve into this host's `tests/_org`, and sandbox paths into its runtime directory. The prior Fresh config remained unchanged at `.waapi-skill-state/runtime/expansion-frozen-live-environment.json` (SHA `f4a672b5007631bead3180125652621fe903c2ca8dafbba0e132431a663b5b6a`). The initially named portable config path under `tests/fixtures/local` was absent; the exact historical plist path was retained.

Operational preflight for future fresh worktrees: hydrate local commit-pinned LFS payloads and verify their OIDs before fixture-dependent gates; restore the ignored default config from trusted bytes and check repository-relative source/sandbox resolution; independently preserve the pinned campaign config. Then require clean exact HEAD, zero test/Fresh/Wwise owners, protected source hash/mtime equality, exact Skill-local interpreter/dependency check, pinned CLI/runtime/config fingerprints and an absent new root before one bootstrap.

Fresh root `expansion-c09-700914d-sol-high-r1-cli1592` used the exact prior direct Python argv except the new root: `integration_expansion_v1`, Wwise 2025.1, EXP25-C09, `gpt-6.1-sol`, high, default tier, timeout 600, readiness 180, and zero pre-action retries. CLI 0.159.2 SHA `16593cc2f422d5f398a8e40f550ebbaf1245392528957be342c295920a300704`, Skill-local runtime distributions and interpreter checks matched preflight. Its LaunchAgent used RunAtLoad true/KeepAlive false, bootstrapped once, ran once, exited 1 and was booted out; no kickstart occurred. Auth contents were never printed.

The sole failing gate was emitted after a notice at event 23. Saved notice:

> 已核对目标声音并记录修改前状态；此次追加已取得 `allow_changes` 策略的独立授权，目前尚未修改。
>
> 即将追加 Wwise Gain 效果器 `Expansion_EXP25-C09_NewGain`，备注为“Expansion C09 appended gain”。执行后将核验现有两个效果器的身份、slot 绑定、配置顺序，以及声音音量、备注和父级的保持情况。

One immutable Preview, Execute and Verify each exited zero. All six independently sealed assertions were true: unchanged owner; one added binding; existing effects/bindings unchanged; matching new effect; unique effect identities; and new-effect ownership. The trusted oracle closed, Gateway state was verified, all other turn gates were true. This executor did not diagnose new code or reinterpret the notice result.

Native audit checked 177 manifest artifacts totaling 6,769,572 bytes and all 11 SHA seals; attempt manifest SHA `4dfb4adf8ed57e9f220a866b2fc1ce1ff07162358999d6e3ce7c1ceccec8fcca`. Audit errors and scoped processes were empty. Both protected source full hashes/project mtimes exactly match the prior guards. Cleanup was cleaned, process exited, residual processes empty. Retained quarantine full-tree SHA `42163aa0f5d03392b416ef6196faf852267c0263fa6b3d3dc51e704d910d5dbc` independently matches its never-reuse seal. The source candidate remained clean.

Fresh usage: 440982 input tokens, 396672 cached and 44310 uncached; 2025 output tokens including 220 reasoning tokens; no reported USD. Historical `0c2e75e` root remains its original notice FAIL with 6/6 business assertions, 96.78919045906514 agent seconds, 441330 input / 402432 cached / 38898 uncached, 2053 output including 304 reasoning, no USD. It was not replayed or regraded.

Durable evidence is under `/Users/xiye/.codex/worktrees/expansion-frozen-campaign/waapi-skills/.waapi-skill-state/evidence/waapi-test-remediation/`, in separate `expansion-nonlive-700914d-r1`, `expansion-environment-recovery-700914d-r1`, `expansion-nonlive-700914d-r2` and Fresh-named directories. The companion JSON supplies exact artifact paths/digests, complete failed-case list, argv, notices, lifecycle and audits. Non-live r2 log SHA `9ff943c3210c5024d0df990d172d61778fc21f9394e49306c5a221e1e524d231`; XML SHA `b04bb7b027c2bbe1462fe012f00ad2dca8dc096ee2edd8cdb51a18b57e0169d9`.

Read-only priority check: the existing CLI exposes no case-priority/order option. The expansion loader creates version-major CASE_IDS order, then filters; selector argv order cannot put C09 first. A targeted root cannot expand its immutable selection into full acceptance. The original targeted-first plan was retained, and full acceptance remains pending after this failure.

Coordination note: every new subagent explicitly uses `fork_turns="none"`, carrying only necessary objective, constraints, acceptance, path pointers and essential unrecorded decisions; propagate recursively. No goal metadata edit is claimed. Per coordinator, 137/138/139/140/142/143 closed on existing component proof and 156 on an explicit unsupported complete-tool-inventory telemetry boundary; 147/122/108 remain open. This executor changed no issues, push or PR.
