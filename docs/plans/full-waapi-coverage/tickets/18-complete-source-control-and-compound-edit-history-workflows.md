# 18: Complete source-control and compound edit-history workflows

Status: approved for implementation on 2026-10-17. Published as [18: Complete source-control and compound edit-history workflows](https://github.com/zcyh147/waapi-skill/issues/192).

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can perform supported source-control and compound edit-history operations through complete closed requests with accurate outcomes and authorization.

## Current simple undo/redo acceptance — user-approved 2026-10-27

Simple undo/redo require accurate lightweight wrappers, callability and code
tests. All available pinned native args/options/result schemas are closed empty
objects (`{}`); preserve that mapping. Public `expectation_receipt` is optional,
and the basic `latest_project_history` path already exists with explicit
result-schema-only verification. This weaker result does not certify graph
restoration and must be disclosed before authorization.

Stop optional complex graph-restoration observer expansion; it is not required
for current acceptance. Retain supported existing observers and their stated
limits. Configuration binding, permissions, immutable Preview, one execution
and truthful uncertainty remain required. This does not resolve the separate
real UndoGroup staged-list admission restriction, provider-dependent work or
compound safety obligations. #192 remains open; no native absence or whole-ticket
completion follows from accepting simple undo/redo.

## Acceptance criteria

- [ ] Map all permitted source-control commands, object/file scopes, provider-dependent choices and undo-group/compound operation alternatives to exact public inputs.
- [ ] Keep filesystem/source-control scope explicit and resolve live provider availability without treating a missing local provider as native impossibility.
- [ ] Preserve child Preview and aggregate authorization semantics, dependency order, execute-once behavior and accurate mixed-strength verification for compound changes.
- [ ] Apply the current lightweight result-schema-only/code-test acceptance to simple undo/redo, retaining existing observers without requiring complex graph-restoration expansion. Verify separate provider and compound outcomes under their applicable acceptance; unavailable providers or missing required evidence keep those branches blocked.
- [ ] Test wrong provider/scope, invalid child composition, partial execution, rollback/cancellation boundaries and uncertain cleanup without replay or invented all-success results.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

## Blocked by

- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.
