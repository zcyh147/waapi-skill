# 07: Complete object queries and metadata discovery projections

Status: approved for implementation on 2026-10-17. Published as [07: Complete object queries and metadata discovery projections](https://github.com/zcyh147/waapi-skill/issues/181).

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can express valid in-scope read semantics and inspect every applicable property/reference detail through bounded public queries and metadata discovery.

## Acceptance criteria

- [ ] Map closed and advanced query sources, relationships, predicates and output alternatives to native semantics, retaining the approved bounded read-only expression boundary and exact-ID follow-up requirements.
- [ ] Complete metadata type/property/reference listing, optional lexical discovery, exact selection/detail, field projection and all reachable result alternatives. Preserve enums, defaults, constraints, applicability, conditions, RTPC support and known/unknown units.
- [ ] Provide complete bounded pages or explicit controlled continuations; reject stale/cross-scope selection and avoid substituting unrelated surviving fields after a rejection.
- [ ] Prove no-match to refined unique match to exact required values through the public CLI, including valid argument forms and self-contained guidance. Required fields must be visible to the Agent, not only known by a fixture.
- [ ] Validate real native acceptance for newly supported query constructs and metadata semantics; distinguish null/absent/malformed values and preserve project state throughout.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.
- [ ] Seal every selected ordinary property/reference's exact native metadata through acquisition, Preview, prewrite and postwrite verification, including dependency-free fields and reference clears. Reuse the shared [03 / #177](https://github.com/zcyh147/waapi-skill/issues/177) metadata assertion guard; preserve native omission versus explicit null, types, restrictions and units. Five-version unchanged controls must succeed; metadata drift before execution must dispatch zero mutations. The #181 audit reproduced unconditional `object.setProperty` metadata drift after Preview (20 failing public controls); the earlier `a0c192d9` Program candidate predates this repair and grants it no acceptance credit.
- [ ] Complete the read → exact selection → Field Handle handoff when native `getPropertyInfo.name` is absent but type is known. Use only the selected token freshly proven by scoped `getPropertyAndReferenceNames`; preserve raw name absence, reject explicit null, mismatched names and stale selections without substituting an unrelated surviving field. Five-version property/reference acquisition must survive durable reload, Preview, prewrite and verification. The #181 public audit reproduced ten acquisition failures on candidate `dcf0ae11`; its Non-live run predates this repair. The narrow canonical metadata binding remains shared with #177.

## Blocked by

- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.

The structured Short-ID type mapping is a shared source-consistency prerequisite with [09 / #183](https://github.com/zcyh147/waapi-skill/issues/183): the Definition resolver's unversioned Event/Effect/AuxBus codes cannot establish the unresolved 2021 query codes. Preserve the exact per-version source proof and keep 2021 pending until reconciled; do not infer codes from PluginID, classId, or later releases.
