# 03: Support native metadata conditions for existing-object changes

Status: approved for implementation on 2026-10-17. Published as [03: Support native metadata conditions for existing-object changes](https://github.com/zcyh147/waapi-skill/issues/177).

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Valid property and reference changes work across applicable object classes because the Gateway understands their native activation conditions, rather than accepting only previously encountered examples.

## Acceptance criteria

- [ ] Inventory the observed five-version condition vocabulary and its semantics from property/reference metadata and matching native sources, including relation, enum, Boolean and nested forms where actually supported.
- [ ] Implement reusable condition evaluation and prerequisite planning; remove class-specific unsupported cases wherever the native semantics are shared. Link every observed valid grammar branch to public-path proof.
- [ ] Make necessary changes visible in the same supported Preview or an explicit separately authorized prerequisite workflow. Deduplicate requirements, preserve already-satisfied fields and never overwrite contradictory user intent silently.
- [ ] Reject conflicting, cyclic, malformed or native-invalid expressions before mutation; valid expressions lacking an implementation remain this ticket’s work, not a completed unsupported boundary.
- [ ] Prove successful property and reference edits across applicable Sound/container/other collected classes, prerequisite readback, unchanged unrelated state, live metadata drift and accurate recovery. Preserve all three policies.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

## Blocked by

- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.

## Execution detail — 2026-10-23

Execution follows the [shared test-selection and evidence-reuse rules](https://github.com/zcyh147/waapi-skill/blob/codex/full-waapi-coverage/tests/semantic/TEST_ACCEPTANCE.md). Scope and existing dependencies remain unchanged.

Next business slice: change an existing 2025 PlaylistSlot.PlaylistObject to a direct child of its owning container through discovery, Change Preview, execution and readback. Reuse the retained R62 field metadata and R63 exact identity packets; the R63 collection's failed report-writing verdict remains unchanged. First repair exact class-bound recognition of the observed unnamed PluginInnerObject, then the owner/membership/target-parent proof and scoped native type-label mapping. Reuse shared reference/identity tests; add focused ordinary-object preservation, class/owner/parent/metadata drift and invalid-target controls. One native effect case on the existing sandbox fixture follows a stable code path. New-slot and older list variants remain under #178/#180; this slice does not close #177.

### Scoped result — 2026-10-23

The above existing-slot flow passed on Console 2025.1.7.9143 at `ee55f8e5`:
one public transaction and independent target, peer and ordered-list readback;
1 native test passed in 6.04s. Affected fake-client checks passed 1291 at
`23008fa31`; the subsequent class-specific rename-boundary checks passed 19 at
`ee55f8e5`. See [the exact test record](../../../../tests/TEST_INVENTORY.md).
No Fresh run was used. The newly bindable unnamed class must not silently gain
rename authority; its native name semantics remain owned by #180, with a truthful
`OBJECT_NAME_MUTABILITY_UNPROVEN` boundary until established. New-slot and older
list variants remain assigned work. This ticket stays open.
