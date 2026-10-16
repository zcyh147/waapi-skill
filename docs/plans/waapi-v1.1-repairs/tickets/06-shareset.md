# 06: Create standalone Effect ShareSets and reject incompatible targets

## Parent

#163

## What to build

The public contract distinguishes an owner-local effect instance from a standalone Effect ShareSet under the Effects Work Unit.

## Acceptance criteria

- [ ] Disclose placement intent and target requirements; select plugin class through live Type Handles.
- [ ] Implement the version-validated Work Unit children topology for standalone ShareSets, separate from owner EffectSlot topology.
- [ ] Reject incompatible target, unavailable plugin and conflicts before writing; never treat a Work Unit as an effect-slot owner.
- [ ] Parse and verify ShareSet identity, parent, plugin type, name and properties independently; an empty result is not success.
- [ ] Cover all 2021.1–2025.1 lanes: implement native-supported branches and explicitly test native-unavailable boundaries (including the existing 2021.1 plugin creation boundary unless evidence establishes a supported lane). Regress owner plugin creation and 2022.1/2025.1 topology differences.

## Blocked by

None

## Validation

Public Gateway tests plus coordinated sandbox ShareSet creation/readback using plugins without additional license prerequisites. Use existing or ticket-local discovery; do not invent a dependency on ticket03. Final F4.

## Execution constraints

The user approved implementation on 2026-10-17. All five supported version lanes must be covered; documented native unavailability is an explicit tested boundary, not silent omission. Use the approved public Gateway/FakeClient seams and TDD. Follow repository guidance and the spec budget. Do not modify the Lyra user project or replay its transactions. Report program, real-Wwise and Fresh evidence separately.
