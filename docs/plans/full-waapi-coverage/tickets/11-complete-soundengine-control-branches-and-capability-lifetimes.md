# 11: Complete SoundEngine control branches and capability lifetimes

Status: approved for implementation on 2026-10-17. Published as [11: Complete SoundEngine control branches and capability lifetimes](https://github.com/zcyh147/waapi-skill/issues/185).

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

- [02: Make branch completion and gap ownership executable](https://github.com/zcyh147/waapi-skill/issues/176)

## Completion boundary

Complete only the exact branch scope and evidence owned by this ticket. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.

## Pinned-source findings from the 2026-10-18 implementation batch

This is partial source research and fake-Gateway implementation evidence, not
completion of this ticket. All 26 owned URI identities and every untouched native
branch remain assigned here. The exact matching source lanes are:

| Wwise lane | Reflected / local SDK build | Reflected SoundEngine function routes |
| --- | --- | --- |
| 2021.1 | 2021.1.14.8108 | 22 |
| 2022.1 | 2022.1.19.8584 | 24 |
| 2023.1 | 2023.1.19.8928 | 26 |
| 2024.1 | 2024.1.13.9056 | 26 |
| 2025.1 | 2025.1.7.9143 | 26 |

The matching SDK's `SDK/include/AK/SoundEngine/Common/AkTypes.h` and
`AkSoundEngine.h` establish these meanings in all five builds:

- `AkCurveInterpolation_Constant = 9` is explicitly **not valid for fading
  values**. The reflected maximum 9 alone therefore does not justify offering
  Constant for `executeActionOnEvent` or `stopPlayingID`. The named fade choices
  remain the legal 0–8 set. This is a primary-source semantic restriction, not a
  guessed enum or a missing-Skill/native-absence claim.
- Every pinned `seekOnEvent.argsSchema.oneOf` requires `event`, `gameObject`,
  `playingId`, `seekToNearestMarker`, and exactly one of `position` or `percent`.
  There is no Event-free native overload in these schemas. A future business
  convenience using only a playing capability would have to derive and
  revalidate its Event; it cannot omit the native Event or weaken identity
  validation.
- `SetRTPCValue` and `ResetRTPCValue` use `AK_INVALID_GAME_OBJECT` for global
  values. This is distinct from the WAAPI 2023.1+ omitted `gameObject`, whose
  reflected default is the transport game object. The explicit global choice is
  now constructible in all five public lanes.
- `UnregisterGameObj` accepts the sentinel to unregister all game objects.
  Unregistering an in-use object is allowed and can leave its sounds playing;
  the SDK says control over that game object's parameters is lost. Unregister
  therefore consumes registration authority and preserves independent playing
  authority; it must not claim that audio stopped.
- `SetGameObjectOutputBusVolume` and `AkAuxSendValue.listenerID` accept the same
  sentinel for all connected listeners. Their gain range is 0 through 16
  (zero is silence, above one amplifies). Closed listener-scope choices and
  percentage 0–1600 now express those branches without numeric native IDs.
- Every pinned `setMultiplePositions` schema permits an empty positions array;
  the SDK uses an unsigned position count. An explicit clear-positions choice
  now distinguishes empty from omitted or populated frame collections in every
  named multi-position mode. Native empty-list effects still need acceptance.

The batch consumes stop/unregister authority only after all prewrite checks and
successful durable `execution_started`, before native dispatch. A failed journal
start preserves the original authority; an uncertain native stop keeps it
consumed and prohibits replay. A shared existing transaction-lease mechanism
serializes SoundEngine control and publication. Immutable exact capability
snapshots prevent an old Preview from following a recycled numeric native ID;
execution-ordered playing reservations also reject delayed publication of an
older lifetime over a newer Event.

These mechanisms attest Gateway ownership and local lifetime transitions. They
do not attest instantaneous native resource existence, natural playing
completion, engine restart at the same endpoint/project/build, queued stop or
fade completion, or native spatial/listener/mix/RTPC/Bank effects. Independent
observers, correct capture/timing prerequisites and matching sandbox-native
acceptance remain implementation/evidence work under this ticket. Existing
Profiler capture reads are not automatically a live-resource oracle. No native
process, network client, Console/Authoring launch or Fresh task was used for
this source batch, and no branch/family completion credit is assigned.
