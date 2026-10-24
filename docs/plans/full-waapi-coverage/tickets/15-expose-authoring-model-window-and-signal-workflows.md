# 15: Expose Authoring model, window and signal workflows

Status: approved for implementation on 2026-10-17. Published as [15: Expose Authoring model, window and signal workflows](https://github.com/zcyh147/waapi-skill/issues/189).

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can use native-supported ordinary Authoring model/window/signal capabilities through complete typed business contracts and owned resource lifetimes.

## Acceptance criteria

- [ ] Cover the applicable model handle/create/destroy/state/registration, window create/present/close and signal emission interfaces from exact native schemas, not guessed forms.
- [ ] Support permitted nested state, property and signal alternatives through the existing controlled construction model; no raw model dump, arbitrary code loader or native JSON escape is added.
- [ ] Bind created handles/windows to their host/session and validate relationships and lifecycle before later calls; do not derive current availability from static command lists.
- [ ] Prove observable state/window effects and signal delivery with appropriate independent evidence and cleanup of owned resources.
- [ ] Cover missing/stale handles, invalid state shapes, wrong host/version, rejected registration fields, partial creation and cleanup failures. The two excluded Authoring ui.cli additions remain excluded.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

## Blocked by

- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.

## Implementation checkpoint — 2026-10-18

The public `request-schema` → `draft-declare-model-plan` → immutable Preview → authorized execute-once → verification path now constructs the nine captured 2024.1/2025.1 model/window/signal functions. The closed constructors cover typed widget/state values, versioned widget/layout definitions, single and named template collections, inline registration and Gateway-generated frozen WAFM files. Owned window/template/frontend receipts bind configuration, host, build, process session and project. Frontends retain their window/template parents; pending creation ownership blocks premature window cleanup. Atomic immutable receipt/tombstone publication uses the existing execution lease. `authoring-resource` recovers cleanup authority from a single sealed successful creation result independently of business-effect verification; rejected registration does not become an owned template.

This is program implementation, not ticket completion. Captured 2021.1–2023.1 Authoring catalogs do not list these exact nine URIs; that fixed-route absence does not establish business absence, and no equivalent custom frontend route has been proved. Exact independent native catalogs remain the schema/provenance authority. No new Authoring/native/Fresh run was started. Independent model state effects, visible/presented/closed window effects, signal delivery after an already-started owned observer, registration/file acceptance, and final native cleanup remain owned unfinished evidence under #189 (observation integration also #187). There is no reflected template unregister route: its cleanup boundary is the owning Authoring session. Neither window result validation nor a successful emit result proves its business effect.
