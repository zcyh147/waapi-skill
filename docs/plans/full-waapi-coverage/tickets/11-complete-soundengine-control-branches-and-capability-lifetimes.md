# 11: Complete SoundEngine control branches and capability lifetimes

Status: draft for user review; not yet published or authorized for implementation.

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can perform every in-scope reflected runtime control through meaningful business inputs, with valid game-object and playing-resource lifetimes.

## Acceptance criteria

- [ ] Map the SoundEngine contract set by URI, version, enum/union meaning and required runtime identity; include registered game objects, playback/event actions, listener/spatial controls, runtime values and other assigned controls.
- [ ] Fill missing permitted scalar, optional, nested and collection inputs without exposing numeric wire guesses, raw requests or unbound runtime IDs.
- [ ] Bind, revoke and revalidate capabilities according to the actual resource lifetime and host; distinguish global scope, object scope and playing scope where native semantics differ.
- [ ] Prove native state/effects with available independent observations; disclose a genuinely native observation limitation without presenting schema-only success as business verification.
- [ ] Cover wrong/stale/revoked capabilities, missing runtime prerequisites, incompatible modes, partial results and resource cleanup. Split an oversized exact URI batch into same-parent children before implementation; none may leave scope.
- [ ] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [ ] Maintain exact owned branch IDs, public input/routing, construction, result/verification alternatives and required evidence, including reachable shared definitions and newly discovered variants. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [ ] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [ ] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

## Blocked by

- Draft 02: Make branch completion and gap ownership executable

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.
