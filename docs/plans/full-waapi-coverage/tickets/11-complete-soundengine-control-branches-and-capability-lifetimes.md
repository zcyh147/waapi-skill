# 11: Complete SoundEngine control branches and capability lifetimes

Status: functional scope accepted on 2026-10-27; [GitHub #185](https://github.com/zcyh147/waapi-skill/issues/185). Final combined gates remain #195.

## Parent

[Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174).

## What to build

Users can perform every in-scope reflected runtime control through meaningful business inputs, with valid game-object and playing-resource lifetimes.

## Current acceptance method — user-approved 2026-10-26

Keep complete legitimate parameter/option support and native-to-public mapping against the five pinned definitions. Aim for one or two representative public cases per meaningful parameter branch or shared mechanism; remaining legal values stay selectable. Mapping leaves, enum values, optional-field permutations and collection sizes are not separate execution-receipt or evidence-ID quotas. Simple APIs use an ordinary happy path and relevant retained proof. Select native work for actual business risk, independent behavior and host/version differences, reusing valid matching observations.

Representative registration/play/control/stop/release flows and materially different global/object/playing scopes; verify available state/effects and shared stale-capability/cleanup boundaries.

CRUD, queries and compound changes retain appropriate identity, policy, execute-once, outcome and cleanup checks. A known Wwise defect or native absence is recorded as an explicit source-supported boundary, not Wwise repair/QA work. Unsupported normal-user functionality remains assigned. This method supersedes stronger proof quotas in earlier execution notes without rewriting their original results. #194 owns Fresh with current budget zero; #195 coordinates required stable-candidate full Program/Non-live gates, not per-ticket sweeps.

## Acceptance criteria

- [x] Map the SoundEngine contract set by URI, version, enum/union meaning and required runtime identity; include registered game objects, playback/event actions, listener/spatial controls, runtime values and other assigned controls.
- [x] Fill missing permitted scalar, optional, nested and collection inputs without exposing numeric wire guesses, raw requests or unbound runtime IDs.
- [x] Bind, revoke and revalidate capabilities according to the actual resource lifetime and host; distinguish global scope, object scope and playing scope where native semantics differ.
- [x] Prove native state/effects with available independent observations; disclose a genuinely native observation limitation without presenting schema-only success as business verification.
- [x] Cover wrong/stale/revoked capabilities, missing runtime prerequisites, incompatible modes, partial results and resource cleanup. Split an oversized exact URI batch into same-parent children before implementation; none may leave scope.
- [x] Account explicitly for Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, with exact host/build provenance and applicable native shapes. A current packaged boundary is not proof of native absence.
- [x] Maintain exact owned native-to-public branch/field/option mappings, including reachable shared definitions and newly discovered variants. Map them to the selected representative mechanism tests and required business proof; do not demand a separate execution or evidence receipt per reflected leaf. In-scope omissions must be implemented here or split into linked same-parent implementation children; they never leave the overall scope.
- [x] Verify the highest existing public Gateway seam with positive and meaningful negative controls. Use sequential owned native tests where behavior needs native proof; preserve source projects and original evidence. No Fresh run is authorized until a separate exact budget is approved.
- [x] Preserve Gateway-owned request construction, configuration binding, the three modification policies, immutable Preview, execute-once semantics and truthful uncertainty. Do not add a raw-input escape or weaken safety to claim coverage.

## Completion boundary

Complete the owned functional scope and selected evidence required by the current user-approved representative testing policy. A native limitation must be supported by matching native evidence and considered alternatives; an implementation or environment limitation remains unfinished. Any required shared implementation discovered during work must become an explicit dependency, not an undocumented ordering assumption.


## Approved prerequisite and batch delivery — 2026-10-25

Blocked by #197. Batch: **C: runtime/event**. Preserve this ticket's implementation scope, applicable 2021.1–2025.1 mappings and native distinctions; apply the current user-approved representative evidence method above. Use the shared prerequisite's deduplicated batch selection, independent outcomes, failed/affected reruns and durable result summaries. Reuse valid original results after relevant dependency review; a commit-number or unrelated documentation change does not require another native run.

Functional tickets use Python tests and proportional real-Wwise validation. Fresh is centralized in #194 with a separately approved exact budget; #195 aggregates those results rather than scheduling a duplicate Fresh campaign. Necessary final combined Program/Nonlive gates are coordinated under #195 rather than repeated per functional ticket.

The required post-#197 report was completed and the user explicitly resumed downstream work; this historical pause is satisfied.


## Functional closeout — 2026-10-27

Closed wrapping covers all **26 owned URIs / 124 reflected version rows** across
2021.1–2025.1. These are structural counts, not native-effect counts. A current
scope audit and independent closeout review found the required public contracts,
version mappings, lifetime controls and available observer paths implemented.
No additional runtime change or new test run was needed for this reconciliation.

| Shared mechanism | All owned `ak.soundengine.*` routes | Acceptance basis |
| --- | --- | --- |
| Registration | registerGameObj, unregisterGameObj | Closed handles/generation/retirement controls and accepted registration/release workflow. |
| Playback | postEvent, executeActionOnEvent, seekOnEvent, stopAll, stopPlayingID | Closed Event/playing scopes and action/fade/seek choices; accepted post/seek/stop/release effects, with per-enum native repetition unnecessary. |
| State/Switch | setState, setSwitch, getState, getSwitch | Bound identities and bounded getters; accepted exact State/Switch GUID readback where supported. |
| Values/trigger | setRTPCValue, resetRTPCValue, postTrigger | Complete business-field mapping and global/object/default scope controls; representative shared dispatch mechanism, not a separate native-effect claim for every route. |
| Listener/spatial | setDefaultListeners, setListeners, setPosition, setMultiplePositions, setObjectObstructionAndOcclusion, setScalingFactor, setGameObjectOutputBusVolume, setListenerSpatialization, setGameObjectAuxSendValues | Closed clear/list/position/gain/layout/offset inputs and meaningful negatives; accepted representative listener/spatial workflow. No acoustic or per-channel QA claim. |
| Banks | loadBank, unloadBank | Bound bank identity, versioned construction and public lifecycle controls; no invented distinct native bank-effect receipt. |
| Monitor | postMsgMonitor | Bounded message/severity and accepted dispatch; observer receipt remains explicitly unproved. |

Current controls in `tests/unit/test_soundengine_business_gateway.py` cover
registry/catalog equality, legitimate field construction, stale/reused/retired
handles, pending publication, conflicting scopes, journal/storage failure,
cleanup and independent State/Switch readback failures. Opaque capabilities
attest Gateway control authority, not continuing native resource liveness.

Accepted representative evidence is reused from
[#88](https://github.com/zcyh147/waapi-skill/issues/88#issuecomment-5465036074)
and [#59](https://github.com/zcyh147/waapi-skill/issues/59#issuecomment-5470272661).
The original `ea36a60` Authoring test was checked for its actual registration,
post/seek/stop/release, spatial/listener and exact State/Switch observations on
2022.1/2025.1 and both hosts. This does not claim current-candidate native reruns,
all-26 independently observed effects or a new Fresh campaign.

Retain the disclosed 2021 State/Switch observation and newer omitted-object
Switch-equivalence limits. They do not prohibit the mapped setter inputs and
are not asserted native absence. The original named raw ledgers are unavailable
in the current local archive; this closeout reuses accepted historical records
without claiming a new transaction-hash revalidation or raw-evidence publication.
#195 owns any required archive/global-inventory reconciliation and final combined
gates. #194 retains separately budgeted Fresh work; its current budget is zero.
No new scope exception, deferred implementation or native QA quota is introduced.

## Retained source and implementation history

The dated record below is preserved unchanged. Its original results remain scoped; the current acceptance method and functional closeout above supersede historical proof quotas, not the recorded facts.

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

Root review of fixed source `49fb1068` found a pending-publication gap despite
its earlier scoped active-handle controls: `postEvent` could execute, then a
separate `stopAll` could execute before the original post was verified, and late
verification would still issue playing authority. The original public RED is
retained. The successor binds Event/game-object provenance and publication state
to each execution-ordered lifetime, and stop consumption invalidates matching
pending receipts as well as active handles. Other Event/object scopes and
unregister preserve publication. A retired/replaced lifetime now reports
`playing_authority_unavailable`, retaining its specific reason, instead of
mislabeling the condition as a filesystem persistence failure. This is authority
bookkeeping evidence only; it adds no native stop/effect acceptance.

A further review of `9fe65fc3` found two local lifetime defects, retained as
separate public REDs. Retired playing lifetime receipts previously accumulated
until the store ceiling blocked every later post, even after all were stopped.
The successor reclaims only receipts already marked unpublishable, under the
same lease, retaining original transaction journals. It checks capacity before
native post dispatch and preserves every active or pending lifetime; late
verification of a reclaimed receipt still fails closed. A lowered-ceiling public
play/stop/capacity control covers both reuse and protection of live authority.

The new all-game-object unregister also needed to invalidate registrations whose
native call had completed but whose public handle had not yet been issued.
Registration execution now journals the exact context's durable unregister-all
epoch. All-game-object unregister advances that epoch only after durable
execution start; late registration verification refuses a mismatched epoch.
This uses bounded per-context state rather than an accumulating registration
receipt per call. A separately executed new registration can bind the new epoch.
Unregister still preserves independently pending or active playing authority,
consistent with the SDK. These repairs remain local Gateway evidence and do not
add native effects or completion credit.
