# 09: Complete SoundBank definition, conversion and build options

Status: functional scope accepted under the 2026-10-27 lightweight method; ready for reviewed closeout of [#183](https://github.com/zcyh147/waapi-skill/issues/183). The fulfilled #179 blocking edge must be removed before closure; remaining #179 plugin work stays open.

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can manage inclusions, process definitions, convert external sources and generate requested banks without wrapper omissions in valid build branches.

## Current acceptance method — user-approved 2026-10-27

Keep complete legitimate parameter/option support and native-to-public mapping against the five pinned definitions. Aim for one or two representative public cases per meaningful parameter branch or shared mechanism; remaining legal values stay selectable. Mapping leaves, enum values, optional-field permutations and collection sizes are not separate execution-receipt or evidence-ID quotas. Simple APIs use an ordinary happy path and relevant retained proof. Select native work for actual business risk, independent behavior and host/version differences, reusing valid matching observations.

Definition-file imports use the user-approved lightweight table policy: complete documented wrapping and representative code tests suffice; do not add native or Fresh tests for table-import combinations. Preserve ordered input files and safety checks, and disclose any weaker result-only verification before authorization without claiming unobserved inclusion/exclusion effects. Conversion and generation retain representative artifact and identity validation. Reuse retained Short-ID repair and test only actual remaining type/version differences.

CRUD, queries and compound changes retain appropriate identity, policy, execute-once, outcome and cleanup checks. A known Wwise defect or native absence is recorded as an explicit source-supported boundary, not Wwise repair/QA work. Unsupported normal-user functionality remains assigned. This method supersedes stronger proof quotas in earlier execution notes without rewriting their original results. #194 owns Fresh with current budget zero; #195 coordinates required stable-candidate full Program/Non-live gates, not per-ticket sweeps.

## Current conversion association boundary — user-approved 2026-10-27

The required setter correction is delivered by reviewed `2a6a8fbd`, integrated
in `c5ba64e5`. It binds an exact Conversion, explicit live project platform and
discovered installed Conversion Type Handle through normal Preview,
authorization, drift checks and one execution. Its disclosed result-only
boundary is `result_schema_checked`, `verified=false`,
`business_state_verified=false`; it produces no codec GUID or automatic scalar
continuation. Getter ambiguity and unobserved native setter effects are accepted
limits; no further platform/codec QA or accessor research is required.

This completes the #179 component needed by #183. Other #179 plugin-kind and
older-construction accounting remains with that issue and does not block this
conversion/build closeout. See the [acceptance note](../../../research/soundbank183-lightweight-closeout.md).

## Acceptance criteria

- [x] Map native SoundBank definition/inclusion alternatives, external-source conversion forms and Core/CLI build options, including nested/repeated bank, platform and language selections. [Accepted scope and proof](../../../research/soundbank183-lightweight-closeout.md#closed-inputs-and-code-controls).
- [x] Preserve default omission versus explicit choices and version-specific names/identities; resolve older nested schema forms using native evidence rather than dropping unfamiliar children. [Accepted scope and proof](../../../research/soundbank183-lightweight-closeout.md#closed-inputs-and-code-controls).
- [x] Keep output roots and referenced input files within declared owned I/O scope; disclose every requested generation/conversion effect in Preview. [Accepted scope and proof](../../../research/soundbank183-lightweight-closeout.md#closed-inputs-and-code-controls).
- [x] Verify actual expected artifacts, inclusion state and relevant metadata under the applicable acceptance method, including the code-only Definition import policy and explicit conversion platform-association limit. A successful process exit or empty result alone is not output verification. [Accepted scope and proof](../../../research/soundbank183-lightweight-closeout.md#retained-artifact-evidence).
- [x] Retain bounded diagnostics, no-retry failure handling and code controls for partial builds, unavailable native setup/plugins, incompatible options, wrong paths and output preservation. Reuse the scoped native artifact failures/successes without claiming a licensed-plugin matrix; source projects remain preserved. [Accepted scope and proof](../../../research/soundbank183-lightweight-closeout.md#closed-inputs-and-code-controls).
- [x] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence. [Accepted scope and proof](../../../research/soundbank183-lightweight-closeout.md#closed-inputs-and-code-controls).
- [x] Maintain exact owned native-to-public branch/field/option mappings, including reachable shared definitions and newly discovered variants. Map them to the selected representative mechanism tests and required business proof; do not demand a separate execution or evidence receipt per reflected leaf. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope. [Accepted scope and proof](../../../research/soundbank183-lightweight-closeout.md#closed-inputs-and-code-controls).
- [x] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved. [Accepted scope and proof](../../../research/soundbank183-lightweight-closeout.md#closed-inputs-and-code-controls).
- [x] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage. [Accepted scope and proof](../../../research/soundbank183-lightweight-closeout.md#delivered-conversion-setter-component).

- [x] Reconcile SoundBank Definition Short-ID resolution with #181 using the retained R89 repair/results first. The earlier audit found an unversioned Event/Effect/AuxBus table and unresolved 2021.1 mapping; this historical finding is not automatically new implementation work. Retain complete release/Definition-type mapping and use existing corrected proof plus representative Short-ID/type readback and wrong-type/ambiguity controls; add targeted checks only for a genuine remaining difference. Do not infer 2021 codes from later definitions, PluginID or classId, and do not count a new unsupported boundary as completion. This is a source-audit inconsistency at `a0c192d9`, not an observed native execution failure. [Accepted scope and proof](../../../research/soundbank183-lightweight-closeout.md#definition-and-short-id-acceptance).


## Completion boundary

The [current acceptance note](../../../research/soundbank183-lightweight-closeout.md)
records complete owned inputs, code-only Definition acceptance, retained
representative artifact proof and the delivered result-only Conversion setter.
No additional #183 implementation or native QA is required by this closeout.
The original combined native FAIL and failed sandboxes remain unchanged.

Main should remove the fulfilled native GitHub blocking edge **#183 → #179**,
retain a normal reference to the other #179 plugin obligations, and close #183
after review. This documentation change performs no issue action. #179 and
parent #174 remain open; #195 owns final global mapping and stable combined
Program/Non-live gates. No Fresh, Windows or full five-version native claim is
added.

### R89 current-source reconciliation — 2026-10-23

The historical Short-ID inconsistency in the added acceptance item is no longer the current implementation. At integrated `ac13a1c9`, `_resolve_definition_identity` calls the shared version-aware `short_id_query(..., unique=True)` and checks exact uint32 Short ID, canonical GUID, uniqueness and expected type. `short_id_query_sources.py` uses matching-source typed WAQL for 2021 rather than borrowing later numeric codes; later documented selectors and the DialogueEvent decimal-comparison repair remain separate.

Existing public Definition Draft/Preview controls in `test_soundbank_business_gateway.py` cover the four supported Definition lanes (2022.1–2025.1), four directive types, wrong-type/Short-ID/GUID and ambiguity cases; this read-only reconciliation does not claim a new test run. `docs/plans/full-waapi-coverage/IMPLEMENTATION.md` R13 and “Repaired Short ID native observation” retain original code and scoped five-version lookup evidence. Read lookup acceptance is not Definition mutation acceptance, nor a claim that the Definition operation exists in 2021. The schema-only numeric-selector test does not prove 2021 semantic type codes.

Do not reimplement the retired unversioned table or repeat accepted lookup tests solely because the original issue text describes that old defect. Remaining Definition mutation/artifact and other SoundBank/conversion branch acceptance still belongs to this ticket; no whole-ticket closure or additional Fresh/native run follows from this correction.


## Approved prerequisite and batch delivery — 2026-10-25

#197 is closed and its required pause/report is satisfied. Batch: **B: media/build/file**. Preserve this ticket's implementation scope, applicable 2021.1–2025.1 mappings and native distinctions; apply the current user-approved representative evidence method above. Use the shared prerequisite's deduplicated batch selection, independent outcomes, failed/affected reruns and durable result summaries. Reuse valid original results after relevant dependency review; a commit-number or unrelated documentation change does not require another native run.

Functional tickets use Python tests and proportional real-Wwise validation. Fresh is centralized in #194 with a separately approved exact budget; #195 aggregates those results rather than scheduling a duplicate Fresh campaign. Necessary final combined Program/Nonlive gates are coordinated under #195 rather than repeated per functional ticket.

The required post-#197 report was completed and the user explicitly resumed downstream implementation. #197 is closed; its historical pause is satisfied.
