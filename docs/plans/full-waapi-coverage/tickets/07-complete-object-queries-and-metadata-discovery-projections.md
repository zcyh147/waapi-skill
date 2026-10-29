# 07: Complete object queries and metadata discovery projections

Status: functional acceptance complete on 2026-10-26, with the explicit boundaries below. Publication and closure are recorded in [#181](https://github.com/zcyh147/waapi-skill/issues/181); final combined gates and mapping reconciliation remain under #195.

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can express valid in-scope read semantics and inspect every applicable property/reference detail through bounded public queries and metadata discovery.

## Acceptance criteria

- [x] Map closed and advanced query sources, relationships, predicates and output alternatives to native semantics, retaining the approved bounded read-only expression boundary and exact-ID follow-up requirements.
- [x] Complete metadata type/property/reference listing, optional lexical discovery, exact selection/detail, field projection and all reachable result alternatives. Preserve enums, defaults, constraints, applicability, conditions, RTPC support and known/unknown units.
- [x] Provide complete bounded pages or explicit controlled continuations; reject stale/cross-scope selection and avoid substituting unrelated surviving fields after a rejection.
- [x] Prove no-match to refined unique match to exact required values through the public CLI, including valid argument forms and self-contained guidance. Required fields must be visible to the Agent, not only known by a fixture.
- [x] Validate real native acceptance for newly supported query constructs and metadata semantics; distinguish null/absent/malformed values and preserve project state throughout.
- [x] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [x] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [x] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [x] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.
- [x] Seal every selected ordinary property/reference's exact native metadata through acquisition, Preview, prewrite and postwrite verification, including dependency-free fields and reference clears. Reuse the shared [03 / #177](https://github.com/zcyh147/waapi-skill/issues/177) metadata assertion guard; preserve native omission versus explicit null, types, restrictions and units. Five-version unchanged controls must succeed; metadata drift before execution must dispatch zero mutations. The #181 audit reproduced unconditional `object.setProperty` metadata drift after Preview (20 failing public controls); the earlier `a0c192d9` Program candidate predates this repair and grants it no acceptance credit.
- [x] Complete the read → exact selection → Field Handle handoff when native `getPropertyInfo.name` is absent but type is known. Use only the selected token freshly proven by scoped `getPropertyAndReferenceNames`; preserve raw name absence, reject explicit null, mismatched names and stale selections without substituting an unrelated surviving field. Five-version property/reference acquisition must survive durable reload, Preview, prewrite and verification. The #181 public audit reproduced ten acquisition failures on candidate `dcf0ae11`; its Non-live run predates this repair. The narrow canonical metadata binding remains shared with #177.

- [x] Deliver native-valid large object-query values losslessly through bounded public result pages; remove avoidable duplicate compact serialization, preserve terminal `agent_result`, and retain `--detail` diagnostics inline or as explicit fragments. Continuations must revalidate the original closed/advanced business read, exact resolved fields, entire native result, selected configuration, project and host session without changing row limits or output semantics. Identity headers retain exact atoms or disclose omissions; their completeness requires every row and all four exact identity atoms. Giant native map keys/pointers must remain recoverable through explicit bounded document fragments, with stable canonical member order, exact Unicode values, and structured changed/resource failures. Fragment/page completion never grants mutation selection or query exhaustion. The `3a7b2c15` public audit reproduced five version-lane failures where valid native notes below the 1 MiB transport ceiling exceeded final output through repeated projections. Its predecessor acceptance cannot establish this repair.

- [x] Repair the same-parent shared Gateway error-contract defect: every `GatewayResultShapeError` call must supply bounded contextual details, preserving intended exact error codes for reachable invalid catalogs, identities, runtime handles/builds and source-control roots. Verification failures must retain already-executed transaction state and prohibit automatic mutation replay. Cover reachable public paths behaviorally and supplement defensive invariant sites with a packaged-call structural guard; do not mask malformed call sites with blanket empty defaults. The immutable `a01599ca` review found fifteen additional omissions; its earlier acceptance predates this repair. Other functional owners and native obligations remain separate.

- [x] Carry exact live type discovery into bounded object queries through the Gateway-issued type selection, including oversized native names and ambiguous loose meanings. Revalidate the exact current raw name, inventory, endpoint, build/session and expiry before query dispatch and on result continuations; preserve optional category/class-ID absence and native extensions. Reject unrepresentable names without constructing an expression. Native `getTypes` membership does not prove WAQL queryability: retain native rejection without aliases or automatic retry, including the unresolved `ObjectSettingAssoc` spelling. This pure-code repair does not establish native acceptance.

## Blocked by

- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.

The structured Short-ID source prerequisite shared with [09 / #183](https://github.com/zcyh147/waapi-skill/issues/183) is resolved for this query path by the version-pinned 2021 typed predicate. Preserve its source proof; unversioned Event/Effect/AuxBus codes, PluginID, classId or later releases are not substitutes.

## Execution detail — 2026-10-23

Execution follows the [shared test-selection and evidence-reuse rules](https://github.com/zcyh147/waapi-skill/blob/codex/full-waapi-coverage/tests/semantic/TEST_ACCEPTANCE.md). Scope and existing dependencies remain unchanged.

Use one parameterized five-version code selection for metadata shapes, query projections, pagination and size/error behavior, adding native reads only for missing native facts. Reuse the recorded metadata observations when their exact scope and source dependencies remain valid. Scope helpers and simulated identities to actual native packets rather than XML serialization names. Test evidence-producer and completion-reader corrections locally through their affected chain; do not repeat a live property query solely to repair an old expectation or report. Keep uncovered query semantics and field alternatives explicit.

## Execution detail — 2026-10-26

Expose the eleven enum-declared legacy return spellings in their five matching
lanes and `states` in 2025.1 through finite closed choices. Preserve actual
response keys and values without claiming equivalent meanings; the user rejected
excluding these choices. Permitted read refinement requires no new approval.

Source-established introduction dates become explicit version restrictions, with
focused code checks rather than older-version native samples. This applies to
the 2023 Source Marker object model; it does not turn unresolved 2021 static RTPC
association or active-source applicability into universal native absence.
Reuse valid observations from the original failed native attempts and preserve
their verdicts. Final combined gates remain under #195 and Fresh under #194.

The user subsequently accepted the precise 2021 stored-property-to-RTPC
association Skill limitation. Schema and early rejection disclose it while
preserving RTPC, Game Parameter and typed ControlInput reads; no universal
native absence is claimed or further undocumented-method search required.
The documented 2021 `SELECT activeSource` was separately rejected by Console
2021.1.14.8108; its exact boundary is disclosed, and file-backed derivation is
retained. Original FAILs remain unchanged. The final review found no additional
functional defect or missing required representative proof. See
`tests/TEST_INVENTORY.md` for the scoped outcomes, including the checks that were
not performed; this acceptance does not establish the parent release gates.
