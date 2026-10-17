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

## Partial source milestones (2026-10-17)

All acceptance boxes remain open. The immutable source milestones are
`bf69ec098a88cf76728a64206a5ba3cc9fd0a302` (seven closed reads, scoped handles,
switch, empty temporary registration/removal, expired-handle reclamation and
integration-test repairs), `9c7c15562dc06169ae1faaf65d2acc3fb4d4859f`
(get-or-create view), and `f414c536867ed5a4ea34586846dc77574c59b78d`
(2025-only close view). These are implementation milestones, not ticket or native
write acceptance.

The public path is `request-schema` followed by its disclosed `layout-read` or
Draft continuation. Mutations take discovered layout/view handles and business
choices. The Gateway owns native identities, payloads, Preview, authorization,
execution revalidation and independent readbacks. Get-or-create preserves omitted
coordinates and verifies reused identities or applicable explicit coordinates.
Close observes exact disappearance with at most sixteen polls, preserves an
explicit `pending_async_close` outcome and never repeats the write. Its 2024
absence is checked against the independently reflected native catalog.

Focused source validation for close passed 179 cases across the full layout
mutation file, affected UI profiles/catalogs, and source inventory/release seams;
its final public handle-role and asynchronous controls passed 9 cases. Those
runs used the same runtime source later committed as `f414c536`; the latter test
run added handle-role controls and a stronger exact pending-result assertion.
Stored combined inventories remain the integration owner's regeneration task.

Owned 2024.1/2025.1 public read observations and exact missing-layout errors have
been captured with original projects and source seals unchanged. They do not
prove setLayout input acceptance or any layout/view write effect. Contradictory
native UI definitions, capital `OneOf`, omitted children and mismatched serialized
fields remain preserved and unresolved. No definition branch has been removed,
normalized globally or credited as native absence.

Remaining work includes the full nested setLayout grammar, dock/undock/splitter,
2025 reset omission/empty/list alternatives, exact reviewed interpretation of
contradictory definitions, owned native write/resource-lifetime observations,
category-v3 observation linkage and exact #176 branch bindings/requirements.
The empty-registration seam does not establish complete layout construction.
Native runs stay sequential and grouped under the existing lifecycle; additional
Authoring launches are on hold because they require user interaction with access
permission windows. Fresh semantic execution remains unauthorized.

## Owned Mac lifecycle strategy milestone (2026-10-17)

The existing ScenarioLifecycle and sandbox launch helper now forward an explicit
Authoring host strategy into HeadlessLifecycle. The strategy pins the exact
2024.1/2025.1 build from the independent native catalog, requires a fresh default
Wine bottle under a private owned HOME, prepares that bottle with the selected
bundle's fixed tools, and binds the copied project through a Wine path roundtrip.
The existing lifecycle retains process ownership, readiness, shutdown and prefix
cleanup. It rejects Console readiness, changed builds, aliased/unowned projects,
changed launch arguments and an existing bottle before accepting a session.
Bounded preparation and readiness records survive launch-proof failure.

Focused fake-only lifecycle, sandbox, shared-batch, category and evidence-reader
controls passed 214 cases. No installed preparation tool, Wwise process or native
client was executed. This is code evidence only. The consolidated pytest driver
still needs to construct and install the actual shared owner; native Windows
process ownership and cross-family integration remain unfinished. No fixture is
claimed launch-ready, and the user interaction hold remains in force.
