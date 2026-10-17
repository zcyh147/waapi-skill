# 13: Complete Topic filtering, event shapes and monitoring outcomes

Status: draft for user review; not yet published or authorized for implementation.

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can monitor every in-scope Topic using its legal filtering/options and obtain correctly validated events and truthful completion status.

## Acceptance criteria

- [ ] Map each Topic’s subscription options, match rules, event payload alternatives and referenced definitions; account separately for subscription setup and event delivery.
- [ ] Complete permitted public Topic construction, including version/host-specific forms and publishing lanes where native capability and the agreed execution policy permit them. A missing public contract is implementation work, not an exclusion.
- [ ] Preserve explicit event-count, total-duration and idle-timeout semantics, bounded output and cancellation/unsubscribe behavior; idle or partial monitoring must not claim target completion.
- [ ] Prove real delivery and cleanup for materially different event mechanisms using owned deterministic triggers. Link any prerequisite new trigger implementation as a genuine dependency rather than faking delivery credit.
- [ ] Cover malformed/mismatched payloads, unknown definitions, wrong host, silence, duplicate/nonmatching events, timeout and cleanup failure through the public monitoring path.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

## Blocked by

- Draft 02: Make branch completion and gap ownership executable

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.
