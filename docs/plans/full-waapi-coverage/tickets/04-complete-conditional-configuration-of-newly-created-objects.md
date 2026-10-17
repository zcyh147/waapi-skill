# 04: Complete conditional configuration of newly created objects

Status: draft for user review; not yet published or authorized for implementation.

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

A user can create an object with its requested valid initial fields even when those fields depend on class defaults or prerequisite settings.

## Acceptance criteria

- [ ] Cover native-supported class-field/default/dependency combinations for new objects, with explicit version and class ownership rather than a GameParameter-only special case.
- [ ] Use class/default evidence for same-call configuration where valid; include explicit user-supplied compatible dependencies and reject real conflicts without making an object.
- [ ] Where native sequencing is required, provide a complete create-then-configure public workflow with a separately previewed authorized change and a verified exact identity between stages.
- [ ] Report partial completion accurately and continue against the verified object; do not duplicate creation, hide post-Preview writes, or replay uncertain transactions.
- [ ] Independently prove requested final fields and preservation on each applicable native lane; include zero-create rejection, metadata/default drift, and interrupted staged-workflow cases.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

## Blocked by

- Draft 03: Support native metadata conditions for existing-object changes

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.
