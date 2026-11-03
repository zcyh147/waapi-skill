# 12: Complete runtime inspection, profiling and transport workflows

Status: approved for implementation on 2026-10-17. Published as [12: Complete runtime inspection, profiling and transport workflows](https://github.com/zcyh147/waapi-skill/issues/186).

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can inspect and control the permitted profiling/transport sessions and receive complete bounded results with correct resource cleanup.

## Acceptance criteria

- [ ] Map runtime-inspection selectors, filters, capture/control alternatives, transport operations and their result branches individually across the supported hosts and versions.
- [ ] Complete fixed, zero-input and parameterized read/control contracts rather than treating empty input or an existing route as sufficient coverage.
- [ ] Preserve capture/session/transport lifetime and pairing rules; setup success is not evidence of requested data, playback state or cleanup.
- [ ] Read back actual state/data where native observation exists, and keep native result-only limitations explicit and justified rather than hiding missing verifier code.
- [ ] Test unavailable sessions, incorrect capabilities, time/row/byte bounds, incomplete results, cancellation and cleanup uncertainty without treating them as successful completion.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

## Blocked by

- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.

## Implementation checkpoint — 2026-10-24 R112

The reviewed RTPC mechanism and standalone evidence package are integrated at
`61e30412`. All 402 RTPC schema branches now have exact public program evidence:
304 meet their requirements, while 98 still require matching native data.
The package includes five-version/two-host structural and optional-result
handling, scalar predicates and the actual ordered cursor-time-to-RTPC query
construction. Legacy native MIDI labels remain unchanged and their compatibility
rule is disclosed after actual row validation. This is not whole-ticket closure.

The 72 actual program receipts passed once in 11.20s. A reporting-count typo
required one evaluation-only recovery using the same package; no tests or
native workflows were repeated. Independent mechanism and artifact reviews
found no remaining scoped issue. Exact results, original native scope and
recovery limits are recorded in `tests/TEST_INVENTORY.md` and the committed
`runtime-rtpc-complete-r112/reader-proof.json`.

Next, bind retained contribution and reader observations through their existing
public business interfaces, grouped by shared implementation. The first
contribution flow is an end-to-end tracer before extending the applicable
five-version lanes, not a separate package per field. Global evidence integration,
the 98 RTPC native-data requirements, other runtime branches and the previously
identified missing native facts remain assigned here. No new Fresh or repeated
native campaign is authorized by this checkpoint.

## Execution note — 2026-10-24

Use [runtime verification decisions](../RUNTIME_VERIFICATION.md) to distinguish
standalone acknowledgement from independently observed effect. Bind the
already-proven runtime reads through the existing evidence reader before
scheduling additional native work. R108 implemented the runtime observation
attachment and completed the 2025 four-mode cursor observation. The next slices
expand exact runtime branch bindings using retained evidence and repair the
confirmed referenced-result validation gaps in the public read paths. Bind
each fact to its actual host/version and keep missing native observations open;
no broad reader rerun or Fresh campaign is authorized by this note.
