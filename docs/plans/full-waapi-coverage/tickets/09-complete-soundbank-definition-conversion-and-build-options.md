# 09: Complete SoundBank definition, conversion and build options

Status: approved for implementation on 2026-10-17. Published as [09: Complete SoundBank definition, conversion and build options](https://github.com/zcyh147/waapi-skill/issues/183).

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can manage inclusions, process definitions, convert external sources and generate requested banks without wrapper omissions in valid build branches.

## Acceptance criteria

- [ ] Map native SoundBank definition/inclusion alternatives, external-source conversion forms and Core/CLI build options, including nested/repeated bank, platform and language selections.
- [ ] Preserve default omission versus explicit choices and version-specific names/identities; resolve older nested schema forms using native evidence rather than dropping unfamiliar children.
- [ ] Keep output roots and referenced input files within declared owned I/O scope; disclose every requested generation/conversion effect in Preview.
- [ ] Verify actual expected artifacts, inclusion state and relevant metadata independently; a successful process exit or empty result alone is not output verification.
- [ ] Exercise partial build failures, unavailable licensed plugins, incompatible native options, wrong paths and output preservation. Existing source projects must remain unchanged in native tests.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

- [ ] Reconcile SoundBank Definition Short-ID resolution with the version-aware read resolver in #181. The current `_resolve_definition_identity` uses an unversioned Event/Effect/AuxBus code table while the read resolver retains an unresolved 2021.1 mapping. Establish matching native mapping or a proved equivalent Gateway-owned resolution for every supported release and Definition type; validate exact Short ID/type readback and wrong-type/ambiguous negatives. Do not infer 2021 codes from later definitions, PluginID or classId, and do not count a new unsupported boundary as completion. This is a source-audit inconsistency at `a0c192d9`, not an observed native execution failure.

## Blocked by

- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.
