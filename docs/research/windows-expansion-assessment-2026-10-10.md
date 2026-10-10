# Native Windows expansion assessment — 2026-10-10

This is the frozen first-pass assessment. The later
[runner repair closeout](windows-agent-command-escaping-2026-10-10.md#native-windows-acceptance-closeout)
proves both previously incomplete C08 business outcomes; original verdicts and
the first-pass table below remain unchanged.

All 13 positive units were attempted once on frozen candidate
`7b4e1164a59f7aff1c17b0771610d49e5760a15e`, across four sequential roots.
The separate M05/2022 capability boundary was also proven. Original verdicts:
**9 PASS / 4 FAIL**. Under the user's approved business-first assessment:
**11 completed / 2 not completed**. This is neither an automated 13/13 PASS
nor complete native-Windows acceptance.

Configuration: standalone Codex CLI 0.162.0; executor and independent reviewer
`gpt-6.1-sol / high / default`; Wwise 2022.1 and 2025.1; existing
`integration_expansion_v1` campaign. SSH controlled desktop-user
`InteractiveToken` / `Limited` Scheduled Tasks. Case policies, Chinese prompts,
budgets, Gateway boundaries and independent Wwise assertions were unchanged.

## Results

| Workflow | 2022.1 | 2025.1 |
| --- | --- | --- |
| C01 localized reimport | PASS | PASS |
| C03 same-basename media mapping | PASS | PASS |
| C06 existing RTPC maintenance | Business PASS; raw FAIL, note 1 | PASS |
| C08 attenuation curve | Not completed; raw FAIL, note 2 | Not completed; raw FAIL, note 2 |
| C09 appended effect | PASS | PASS |
| M01 music import | PASS | PASS |
| M05 Stinger reference | Expected capability boundary; no Agent PASS credit | Business PASS; raw FAIL, note 3 |

1. **C06/2022:** all seven independent business assertions passed and the
   transaction reached `verified`. All 11 Broker calls were authenticated,
   accepted and successful; policy and modification-scope checks passed. One
   Draft command used a differently escaped absolute runner path rather than
   copying the disclosed prefix exactly. The copy gate rejected it and prevented
   notice review. The visible notice described the requested midpoint change;
   the final answer did not overclaim preservation checks. Retain the raw FAIL
   as command-copy compliance evidence, with business completion separately
   recognized. No parser or copy rule was relaxed.
2. **Both C08 units:** the Agent doubled backslashes in the relative runner
   path. The returned prefix contained single separators. Broker rejected the
   command before plan preparation, Preview or Execute, and both Agents stopped
   without claiming completion. No Wwise modification occurred. These are
   incomplete Agent operations, not wording failures. Leave repair/retest to
   the user; neither failed unit was rerun.
3. **M05/2025:** all six independent business assertions and every material
   authorization/provenance gate passed. Only the notice gate failed with
   `unbound-pre-execution-draft-discovery-evidence`. Diagnosis found that the
   authenticated `MusicStinger` bound object had the valid empty name `""`,
   while the discovery-fact validator incorrectly required every name to be
   nonempty. The visible Preview and final answer correctly described the
   trigger replacement and preserved segment/owner. This is a framework defect.

## Framework repair and proportional validation

The discovery validator now uses the packaged `object_identity_semantics` for
empty-name admission. Only reviewed types can be unnamed; ordinary Bus names,
missing/non-string names or types, unknown/case-mismatched types and invalid
handles remain rejected. Receipt authentication, Draft revision lineage,
Preview binding, byte bounds and grounded reviewer judgments are unchanged.
The regression uses a real Gateway-produced unnamed MusicStinger binding with
fake WAAPI responses, then exercises reviewer input and read-only archive replay.

The regression reproduced the old rejection before the fix. Final validation:
**2485 passed** across affected macOS notice, archive, task and authorization
files (26.40 s), and **88 passed** in the native-Windows discovery file
(30.70 s). The packaged Skill is unchanged. The correction is prospective:
no frozen FAIL was rewritten or replayed, and no paid Agent or full batch was
rerun after it. These are focused checks, not another full Non-live gate.

Earlier prerequisite fixes and their validation are recorded in
[Windows portability](windows-expansion-portability-2026-10-10.md) and
[reviewer stdin](windows-reviewer-stdin-2026-10-10.md). The prior full Non-live
run is not claimed all-green: its obsolete typed-container transport fixture
remains a separately documented test-maintenance item for user review.

## Evidence and cleanup

All roots are under `C:/w/exp-7b4e1164/skills/waapi-skill-workspace/`:

| Root suffix after `iwin-expansion-7b4e1164-` | Original result | Replay |
| --- | --- | --- |
| `c01-r1` | 1 PASS | Identical verify-only passed |
| `rest-r1` | 1 PASS, 2 FAIL, 1 boundary; nine pending | Frozen; no replay |
| `pending9-r1` | 5 PASS, 1 FAIL; three pending | Frozen; no replay |
| `pending3-r1` | 2 PASS, 1 FAIL; none pending | Frozen; no replay |

Each continuation selected only units never attempted in an earlier root.
All 14 lifecycle records prove unchanged full source hashes and project mtimes.
The nine raw-PASS sandboxes were removed; four raw-FAIL sandboxes and the
expected-boundary sandbox remain quarantined. Final scoped process and
Scheduled Task counts are both zero. Task-specific launchers were archived
before removal. A 1597-file manifest preserves the four campaign roots.

The compact [machine record](windows-expansion-assessment-2026-10-10.json)
contains individual assertions, raw failures, lifecycle proofs and evidence
locations. Full manifests and final residual checks are retained under
`.waapi-skill-state/evidence/windows-expansion-7b4e1164-assessment` on Windows
and `windows-expansion-7b4e1164-closeout` in the Mac development checkout.

Completed cases reported a mean cumulative Agent time of 122.31 seconds
(range 91.55–184.47), excluding the two early C08 failures. These are reported
Agent durations, not end-to-end campaign wall time or completed phase telemetry.
