# Integration expansion acceptance — #108 / #122

**Accepted under the user-approved completion amendment, 2026-10-09.** The user approved closure after the notice-framework repair and one new EXP25-C09 PASS with identical successful-root audit, without another full matrix. Detailed phase telemetry is deferred. The repair candidate passed its required targeted validation and identical audit. Historical overall verdicts remain unchanged. The [specification](../specs/authoring-integration-expansion.md) and [checkpoint](../specs/authoring-integration-implementation-checkpoint.md) retain the approved scope and historical decisions.

## Frozen candidate and final selection

Repair candidate: `5562104c7b2ba5e689744fb3e832b14eec62739c`; prior full business-evidence candidate: `8079061878ed10254d4b674b4f3885b66b480203`; packaged Skill tree: `10c034a0615ce41d84f61d3614546457b8aa5f8d`. Profile: [`integration_expansion_v1`](../../tests/semantic/data/integration-expansion-v1/profile.json), SHA-256 `26bf5496fa8cdc7c4221bcb7287f1c37fcc15a71ccdf097d251ee4fcadedaf98`. Executor: GPT-6.1 Sol/high/default; limited notice reviewer: GPT-6.1 Sol/high/default (prospective v8); standalone Codex 0.159.2. Fresh tasks use isolated copied projects and the existing formal harness on macOS, sequentially across Wwise 2022.1 and 2025.1.

| Initial case / independent outcome | Permission | 2022.1 business evidence at 8079061 | 2025.1 business evidence at 8079061 |
| --- | --- | --- | --- |
| C01 — replace Japanese dialogue media; preserve English, language set, identities and playback references | ask_before_changes | PASS | PASS |
| C03 — replace same-basename media at exact objects; preserve identities, destinations and unrelated media | ask_before_changes | PASS | PASS |
| C06 — update existing ordered RTPC points; preserve binding, sibling curves, owner/control and media | allow_changes | PASS | PASS |
| C08 — selected attenuation curve; preserve other curves, identity, users/references and source attenuation | allow_changes | PASS | PASS |
| C09 — append one Gain effect; preserve existing effects/bindings and owner | allow_changes | PASS | PASS |
| M01 — imported Segment/Track/Source, Sequence/Clip and media associations; requested Track property only | allow_changes | PASS | PASS |
| M05 — change existing Stinger Trigger; preserve Segment and other configuration | allow_changes | BOUNDARY_PROVEN | PASS |

The completed baseline selection was **13 positive Fresh tasks, 17 user turns and 13 transactions**, plus runner-only EXP22-M05 with zero Agent turns/transactions. The 2022 boundary established unavailable public Trigger/Segment disclosure with unchanged identity; it receives no successful-mutation credit and does not establish native Stinger impossibility. C08 Gateway verification remains `result_schema_checked`; independent runner readback supplies business proof. C09 promises append behavior, not arbitrary effect reordering. Music acceptance covers structure/configuration, excluding playback, listening and runtime beat behavior. Windows acceptance is separate.

## Investigations and retained candidates

All three priority investigations have explicit dispositions, **not complete feature acceptance**. See [dispositions](music-expansion-dispositions-2026-10-01.md), [oracle gaps](music-expansion-oracle-gaps-2026-10-01.md) and [native evidence](music-native-maintenance-evidence-2026-10-02.md).

| Investigation | Established narrow evidence | Remaining scope |
| --- | --- | --- |
| M03 Playlist order/loops | Reads in both lanes; exact 2022 LoopCount 1→2 | Additional reviewed arrangement seam and independent recursive occurrence/order/Segment/finite-state oracle. 2025 dependency maintenance remains unsuccessful; FIELD_DISABLED does not prove feature impossibility. |
| M04 Transition timing/fades | Populated post-exit boolean edit in both lanes; saved XML preserved 15-rule order, 14 siblings, references/fades/music/media | Complete context/exit/sync/cue and fade-role/unit/conversion proof; additional Gateway scope depends on probes. Enabled fields alone prove no timing semantics. |
| M06 Music Switch paths | 2025 keyed reads and one existing AudioNode retarget, with 12 preservation assertions | Authoritative ordered groups/tuples and complete mapping oracle; 2022 maintenance remains unproven. Its unknown-property errors bound the attempted accessors only. No general tuple compiler or new-path creation. |

Those developer-native results belong to historical `78c3587` on macOS 2022.1.19/8584 and 2025.1.7/9143, granting no Fresh Agent/current-candidate whole-workflow credit. Further runtime scope needs separate agreement.

C02 defaults/exceptions and C05 routing reuse existing cases. C07 State configuration, C10 populated music relocation/reference preservation, C11 actual platform link/value differences and M02 Track/Clip/Source parameter maintenance remain conditional, with complete versioned oracles still required. C04 complete Dialogue Event mapping is deferred; C01 localized reimport does not complete it.

## Evidence layers and model decision

Audited Python gaps now cover public create conflict/replacement ownership and no-write Preview; inline/file subordinate media; request-level object.set globals; reused source-note/Originals assertions. Direct Action creation is explicitly `ACTION_CREATION_UNAVAILABLE` under #123, not positive creation-timing coverage; existing edits and import-generated Actions retain separate contracts. These are mapping/fail-closed proofs, not provider-effect claims. Fixtures, independent oracles, profiles, archives, timing and notice adjudication are infrastructure, not extra business cases.

The original matched pilot used 2025 C01/C06/M01: Luna/high and Sol/medium each passed 3/3; conditional Luna/medium retained 2 PASS/1 genuine continuation-copy FAIL despite correct outcomes. Historical selection was Luna/high/default. Later policy-authorized workflows exposed confirmation stops and notice-grading problems; the coordinator prospectively selected Sol/high and the approved limited outcome-blind reviewer. This preserves the pilot, does not rank all models, and establishes no statistical reliability. Deterministic safety, identity, phases, values and preservation remain mandatory under the [notice contract](../../tests/semantic/NOTICE_ADJUDICATION.md).

The original full root `expansion-full-8079061-sol-high-r1-cli1592` retains **12 overall PASS / 1 notice-only FAIL / 1 separate boundary**. All 13 positive units reached verified and passed every required independent business assertion. EXP25-C09 passed its six business assertions and every turn gate except `visible_preview_notice`; the reviewer lacked an authenticated Draft type-discovery receipt. Its final response reported the created Gain and honestly limited what its own readback established. The old root remains frozen, without verify-only or regrading.

The new repair supplies bounded authenticated type/field discovery facts with exact Draft-to-Preview lineage, distinguishing metadata acquisition from a proven fresh network call. It also preserves producer-normalized meaning matching and authenticated failed-discovery/refinement histories without claiming failed acquisitions as facts. Both incremental independent Spec/Standards findings were closed. Focused repair proof passed 360 tests. Fake judgments prove evidence plumbing, not language accuracy. Product Skill bytes are unchanged. The final composed independent review at 8079061 had no unresolved findings; the discovery addition and its corrections received separate incremental reviews.

## Final validation and cleanup

The repair candidate passed **Full Non-live: 17254 passed, 120 skipped, 27 deselected**, exit 0, 920.46 s. The retained log SHA-256 is `96cc8052a898589dee0060f5653f2da5804155855070f0386044cdcab0f94eca`. No new fixed Program run is claimed; the packaged Skill remains byte-identical to the broadly reviewed baseline.

Fresh root `expansion-c09-25-5562104-sol-high-r1-cli1592` passed **EXP25-C09**. All six independent business assertions passed. The isolated v8 reviewer actually ran and accepted the notice; its input contained the authenticated `draft-discover-types` Wwise Gain/effect candidate, with session-bound acquisition and unattested fresh-network-fetch semantics. This proves the repaired evidence path was used, rather than a deterministic shortcut. Agent time 108.924985 s; reviewer 67.583833 s; no slow flag.

The audit checked 69 artifacts / 1,845,852 bytes and 11 sidecar seals with zero integrity errors. Identical `--resume --verify-only` exited0, invoked no model/Wwise work, and left all 84 root files byte-identical. Source full hash and project mtime remained unchanged; the owned sandbox was removed, the one-shot LaunchAgent unloaded, its temporary plist removed and scoped residual processes empty. There is no final-candidate full-matrix claim.

The [machine-readable acceptance record](integration-expansion-acceptance-2026-10-09.json) contains exact candidate, evidence paths, original per-unit grades, business assertions, usage, gate hashes and cleanup/audit results. This completes #147/#122/#108 under the user's amended scope. Minor wording is separated from business failure; material misrepresentation, authorization violations and actual incorrect changes remain unacceptable.

Baseline full-run wall time was 2675 s (44m35s). Across 13 Agent units, cumulative Agent time was 1832.6653 s, mean 140.9743, median 113.7848, maximum 322.1906, with no slow flag. The 13 independent reviewers took 539.0444 s. Executor input 12,594,709 includes cached 11,688,832; output 44,950 includes reasoning 4,461. Reviewer input 349,577, output 13,259 includes reasoning 6,840, cached 0. These are measured usage classes, not additive billing figures or a price/model ranking.

Startup, preparation, oracle and cleanup phase measurements were not complete in the baseline. They are explicitly deferred under the user's amendment; no values are invented. Incomplete code is preserved on `expansion-phase-timing` at 7308f2a, with its remaining six RED regressions, and is excluded from delivery. Existing Agent 600s cumulative / slow 420s, reviewer 120s, readiness 180s and zero automatic pre-action retry limits remain unchanged.

The baseline source hashes/mtimes were unchanged in all 14 lifecycle records; 12 overall PASS sandboxes were removed and the notice-FAIL plus boundary evidence retained. All 1179 sealed artifacts and 11 sidecars were checked again without rejudging the root. The new `baseline-business-assessment.json` separately records the user-approved business interpretation and each original verdict. Targeted repair evidence remains distinct.
