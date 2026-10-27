# 09: Complete SoundBank definition, conversion and build options

Status: approved for implementation on 2026-10-17. Published as [#183](https://github.com/zcyh147/waapi-skill/issues/183). Native GitHub dependencies determine readiness.

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can manage inclusions, process definitions, convert external sources and generate requested banks without wrapper omissions in valid build branches.

## Current acceptance method — user-approved 2026-10-26

Keep complete legitimate parameter/option support and native-to-public mapping against the five pinned definitions. Aim for one or two representative public cases per meaningful parameter branch or shared mechanism; remaining legal values stay selectable. Mapping leaves, enum values, optional-field permutations and collection sizes are not separate execution-receipt or evidence-ID quotas. Simple APIs use an ordinary happy path and relevant retained proof. Select native work for actual business risk, independent behavior and host/version differences, reusing valid matching observations.

Definition-file imports use the user-approved lightweight table policy: complete documented wrapping and representative code tests suffice; do not add native or Fresh tests for table-import combinations. Preserve ordered input files and safety checks, and disclose any weaker result-only verification before authorization without claiming unobserved inclusion/exclusion effects. Conversion and generation retain representative artifact and identity validation. Reuse retained Short-ID repair and test only actual remaining type/version differences.

CRUD, queries and compound changes retain appropriate identity, policy, execute-once, outcome and cleanup checks. A known Wwise defect or native absence is recorded as an explicit source-supported boundary, not Wwise repair/QA work. Unsupported normal-user functionality remains assigned. This method supersedes stronger proof quotas in earlier execution notes without rewriting their original results. #194 owns Fresh with current budget zero; #195 coordinates required stable-candidate full Program/Non-live gates, not per-ticket sweeps.

## Current conversion association boundary — user-approved 2026-10-27

Existing conversion-getter attempts are sufficient; stop further platform/codec
QA and research. Their ambiguous results cannot independently prove which codec
belongs to a platform. Correctly wrap the setter through the pinned closed
contract and code tests; the setter code adjustment remains required. Disclose
the independent platform-association verification limit before authorization,
without guessing codec IDs or asserting a stronger verified effect. Reuse
existing observations only for their actual facts; ambiguity is not native
absence. Preserve configuration, policies, immutable Preview, execute-once and
truthful uncertainty. This acceptance boundary does not close #179 or #183,
and does not remove other plugin placement or conversion/build input work.

## Acceptance criteria

- [ ] Map native SoundBank definition/inclusion alternatives, external-source conversion forms and Core/CLI build options, including nested/repeated bank, platform and language selections.
- [ ] Preserve default omission versus explicit choices and version-specific names/identities; resolve older nested schema forms using native evidence rather than dropping unfamiliar children.
- [ ] Keep output roots and referenced input files within declared owned I/O scope; disclose every requested generation/conversion effect in Preview.
- [ ] Verify actual expected artifacts, inclusion state and relevant metadata under the applicable acceptance method, including the code-only Definition import policy and explicit conversion platform-association limit. A successful process exit or empty result alone is not output verification.
- [ ] Exercise partial build failures, unavailable licensed plugins, incompatible native options, wrong paths and output preservation. Existing source projects must remain unchanged in native tests.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned native-to-public branch/field/option mappings, including reachable shared definitions and newly discovered variants. Map them to the selected representative mechanism tests and required business proof; do not demand a separate execution or evidence receipt per reflected leaf. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

- [ ] Reconcile SoundBank Definition Short-ID resolution with #181 using the retained R89 repair/results first. The earlier audit found an unversioned Event/Effect/AuxBus table and unresolved 2021.1 mapping; this historical finding is not automatically new implementation work. Retain complete release/Definition-type mapping and use existing corrected proof plus representative Short-ID/type readback and wrong-type/ambiguity controls; add targeted checks only for a genuine remaining difference. Do not infer 2021 codes from later definitions, PluginID or classId, and do not count a new unsupported boundary as completion. This is a source-audit inconsistency at `a0c192d9`, not an observed native execution failure.

## Completion boundary

Complete the owned functional scope and selected evidence required by the current user-approved representative testing policy. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.


### R89 current-source reconciliation — 2026-10-23

The historical Short-ID inconsistency in the added acceptance item is no longer the current implementation. At integrated `ac13a1c9`, `_resolve_definition_identity` calls the shared version-aware `short_id_query(..., unique=True)` and checks exact uint32 Short ID, canonical GUID, uniqueness and expected type. `short_id_query_sources.py` uses matching-source typed WAQL for 2021 rather than borrowing later numeric codes; later documented selectors and the DialogueEvent decimal-comparison repair remain separate.

Existing public Definition Draft/Preview controls in `test_soundbank_business_gateway.py` cover the four supported Definition lanes (2022.1–2025.1), four directive types, wrong-type/Short-ID/GUID and ambiguity cases; this read-only reconciliation does not claim a new test run. `docs/plans/full-waapi-coverage/IMPLEMENTATION.md` R13 and “Repaired Short ID native observation” retain original code and scoped five-version lookup evidence. Read lookup acceptance is not Definition mutation acceptance, nor a claim that the Definition operation exists in 2021. The schema-only numeric-selector test does not prove 2021 semantic type codes.

Do not reimplement the retired unversioned table or repeat accepted lookup tests solely because the original issue text describes that old defect. Remaining Definition mutation/artifact and other SoundBank/conversion branch acceptance still belongs to this ticket; no whole-ticket closure or additional Fresh/native run follows from this correction.


## Approved prerequisite and batch delivery — 2026-10-25

Blocked by #197. Batch: **B: media/build/file**. Preserve this ticket's implementation scope, applicable 2021.1–2025.1 mappings and native distinctions; apply the current user-approved representative evidence method above. Use the shared prerequisite's deduplicated batch selection, independent outcomes, failed/affected reruns and durable result summaries. Reuse valid original results after relevant dependency review; a commit-number or unrelated documentation change does not require another native run.

Functional tickets use Python tests and proportional real-Wwise validation. Fresh is centralized in #194 with a separately approved exact budget; #195 aggregates those results rather than scheduling a duplicate Fresh campaign. Necessary final combined Program/Nonlive gates are coordinated under #195 rather than repeated per functional ticket.

The required post-#197 report was completed and the user explicitly resumed downstream implementation. #197 is closed; its historical pause is satisfied.
