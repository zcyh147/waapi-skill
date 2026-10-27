# 14: Expose complete ordinary Authoring layout and view workflows

Status: approved for implementation on 2026-10-17. Published as [14: Expose complete ordinary Authoring layout and view workflows](https://github.com/zcyh147/waapi-skill/issues/188).

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can inspect and manipulate the reflected ordinary Authoring layouts and views through controlled Gateway operations on the correct Wwise host.

## Current acceptance method — user-approved 2026-10-27

Layout UI is low priority. Use lightweight development: reuse existing
source/code and matching native facts, complete accurate versioned closed
wrapping and code controls, and stop further vendor QA. Preserve known height,
sidebar, frontend and schema limitations explicitly rather than guessing native
behavior. This supersedes earlier native write/resource-lifetime proof
requirements and historical remaining-work lists only as acceptance depth;
missing supported inputs and wrapper defects remain owned here. Existing
observations retain only their actual facts; failure to observe an effect does
not establish native absence. Disclose any weaker verification before authorization. Keep
configuration/policy/Preview/execute-once controls and existing observers. This
decision does not complete #188 or authorize a native/Fresh run.

## Acceptance criteria

- [ ] Cover the applicable layout/view reflection set, including names/current layout, layout contents, element rectangles, view types/instances/handles, create-or-get, switch/set/remove, dock/undock/splitter movement and version-specific close/reset variants.
- [ ] Expose closed business choices and scoped instance identities; distinguish discovered availability from a historical catalog snapshot and keep host detection automatic.
- [ ] Implement valid nested/optional layout and view alternatives with Preview/authorization where changes occur; preserve unrelated user state and use owned test layouts/views.
- [ ] Apply the current lightweight acceptance method to layout/view state and resource lifetime: retain available observations and code controls, disclose unproved arrangements and known limitations, and do not require further vendor QA. A returned handle alone is not proof of every requested arrangement.
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
client was executed. This is code evidence only. The existing pytest driver now constructs and installs the shared owner only
after a successful exact collection; native Windows process ownership and
cross-family integration remain unfinished. No fixture is
claimed launch-ready, and the user interaction hold remains in force.


## Exact collected owner installation milestone (2026-10-17)

The existing destructive test driver accepts an explicit
`--owned-authoring-batch-root` pytest option for one Mac 2024.1/2025.1 lane.
It dispatches only the explicitly selected owner-aware layout nodes. The existing
pytest collection hook waits for all collection hooks to succeed, rejects empty,
changed, unrelated, filtered or parallel selections, and creates one existing
ScenarioLifecycle owner. Collect-only and setup-plan allocate nothing. A source
seal is checked before allocation, again under the lifecycle lock before launch,
and through existing adapter finalization. Startup or installation failure never
becomes acceptance; adapter installation failure stops the owner as BLOCKED.

Focused fake-only driver, collection-order, lifecycle, shared-batch, category and
evidence-reader validation passed 253 cases; 11 native-Windows batch-script
parity cases were skipped on this Mac. No native process or installed preparation
tool was executed. This closes the Mac source plumbing milestone for the five
currently owner-aware layout nodes, with real startup/effect proof still pending.
Windows ownership and other families remain explicit unsupported integration
requirements. The five-node roster grants no complete-layout or native credit.


## Closed nested constructor partial (2026-10-17)

The existing setLayout Draft accepts a bounded local-key stack/view blueprint.
The Gateway owns generated IDs, native keys, live view-type validation, immutable
materialization and complete requested-field/order readback. A separate optional
workspace name expresses the inner Layout.Name without forcing equality to its
temporary lookup name; omission deliberately uses the latter as a convenience.
The matching SDK getLayout example documents differing names but grants no
native write/overwrite proof. Focused fake controls passed 47 cases; a further
maximum-depth RED exposed the serialized readback limit and passed after the
business ceiling was tightened to 14, preserving existing native bounds.

This is a constructor milestone only. Typed editor/sidebar state choices and
changes, floating windows, all eight history lists, view-specific state, splitter
and tab-panel contradictions, reset omission/empty/list behavior and host-specific
effect evidence remain owned here. Opaque observed-state reuse does not complete
new state creation. All acceptance boxes and native requirements remain open.

Constructor resource follow-up (code/fake proof only): compiled expansion, Draft
seals and exact terminal request rendering now have separate disclosed bounds.
The closed setLayout blueprint alone may use a bounded 280 KiB verify envelope
(existing 256 KiB seal allowance plus 24 KiB framing); ordinary operations and
small constructors retain 24 KiB. Every admitted request must fit its terminal
request allowance before writes, preserving exact immutable request/agent_result
and raw journal readback. The current 112 KiB business/compiled constructor
ceilings and 14-level tree depth are Gateway resource gaps, not native absence.
Larger legitimate native constructions, downstream Broker/Fresh reply acceptance
and complete editor/sidebar/window/history/reset semantics stay owned here.

Immediate identity repair keeps accepted divergent workspace constructions
inspectable/reusable: the public reply separates lookup layout_name from observed
workspace_name, while existing scoped capabilities retain exact lookup plus full
observed document/hash. Both version lanes fake-test create/verify/inspect and
separate removal; stale document/lookup and cross-layout authority checks remain
strict. Downstream larger-output Gateway/Broker/archive acceptance is an explicit
already-dependent OPEN #194 condition; CLI byte fit grants no such acceptance.

Omitted native Layout is separately unavailable for identity issuance: inspection
requires an observed Layout object and string workspace Name before creating any
handle. This guard does not equate lookup/workspace names. Public versioned
negative controls prove a deliberate structured error and zero new handle files.
