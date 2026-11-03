# 13: Complete Topic filtering, event shapes and monitoring outcomes

Status: approved for implementation on 2026-10-17. Published as [13: Complete Topic filtering, event shapes and monitoring outcomes](https://github.com/zcyh147/waapi-skill/issues/187).

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

- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)

## Completion boundary

The partial monitoring implementation, independent five-version catalog
comparison, exact 2025 Notes-shape probe and outstanding native/#189 trigger
dependencies are recorded in [Topic monitoring](../TOPIC_MONITORING.md). That
checkpoint does not close this ticket or grant native/Fresh coverage.

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.

## Execution detail — 2026-10-23

Execution follows the [shared test-selection and evidence-reuse rules](https://github.com/zcyh147/waapi-skill/blob/codex/full-waapi-coverage/tests/semantic/TEST_ACCEPTANCE.md). Scope and existing dependencies remain unchanged.

Group native delivery cases by materially different trigger/host behavior, keeping each Topic's subscription, filtering, event-content and cleanup assertions separate. A single observed event may support multiple exact payload obligations; unobserved alternatives retain no native credit. Use code tests for malformed payloads, nonmatching events, count/idle/total timeout and cleanup-error handling. Reuse existing matching-host receipts where valid, and implement missing triggers through their linked dependencies. Branch counts are not a requested count of separate native or Fresh runs.

## Lightweight acceptance reconciliation — 2026-10-27

The five-version Topic contracts, recursive construction repair and shared monitoring controls, together with retained scoped event/Notes observations, satisfy the current lightweight acceptance method. The #189 UI dependency is reconciled through its owned resource/trigger contract and the existing subscription controls; no new click/toggle campaign is required. No additional ordinary input gap was identified in this reconciliation. This does not grant native delivery credit to unobserved payload alternatives.

See [the closeout note](../AUTHORING_MODEL_TOPIC_CLOSEOUT.md) for exact scope, retained proof and limitations. This successor assessment supersedes earlier required-effect quotas for these lightweight wrappers without changing historical results. No native or Fresh run is authorized; #195 retains combined gates and inventory reconciliation.
