# 14: Expose complete ordinary Authoring layout and view workflows

Status: approved for implementation on 2026-10-17. Published as [14: Expose complete ordinary Authoring layout and view workflows](https://github.com/zcyh147/waapi-skill/issues/188).

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can inspect and manipulate the reflected ordinary Authoring layouts and views through controlled Gateway operations on the correct Wwise host.

## Acceptance criteria

- [ ] Cover the applicable layout/view reflection set, including names/current layout, layout contents, element rectangles, view types/instances/handles, create-or-get, switch/set/remove, dock/undock/splitter movement and version-specific close/reset variants.
- [ ] Expose closed business choices and scoped instance identities; distinguish discovered availability from a historical catalog snapshot and keep host detection automatic.
- [ ] Implement valid nested/optional layout and view alternatives with Preview/authorization where changes occur; preserve unrelated user state and use owned test layouts/views.
- [ ] Verify actual layout/view state and resource lifetime using native observations appropriate to each operation. A returned handle alone is not proof of every requested arrangement.
- [ ] Test native version absence, wrong host, stale view/layout handles, invalid nesting and cleanup. Ordinary layout switching remains in scope rather than being excluded as custom UI complexity.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

## Blocked by

- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.
