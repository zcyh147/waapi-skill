# Complex interactive-music authoring: bounded risk review

Date: 2026-09-14. Inspected repository HEAD: `7c272d1`. Documentation and static-code review only: no runtime changes, tests, Wwise calls, or new acceptance credit.

## Practical conclusion

The MusicTrack import repair does not establish reliable playlist, transition-rule, or Stinger editing. These features couple inner-object topology, references, ordered rules/items, and playback timing. Creating an object or reading back scalar properties is a weaker result than proving the intended music behavior.

### Music playlists: topology and ordering need their own proof

The official 2025.1.7 SDK example creates a MusicPlaylistContainer with `@PlaylistRoot`, a MusicPlaylistItem root and child MusicPlaylistItem entries, with `PlaylistItemType` and a `Segment` reference. It does **not** use PlaylistSlot for this music tree. Source: local `2025.1.7_en/WwiseSDK-Windows_01.pdf`, physical pp619–620, “Creating a Music Playlist Container with segment and playlist.” The MusicPlaylistItem property tables document group/segment item type, Sequence/Random Continuous/Step modes and loop/repetition controls: 2022.1.19 SDK part 03 p609; 2025.1.7 SDK part 05 p593. Their documented LoopCount lower bound differs (-1 versus 0), another reason to avoid copying scalar assumptions across versions.

The 2025 object-list migration is real but scoped: `@Playlist` becomes PlaylistSlot/PlaylistObject; Music Switch `@Arguments` becomes MusicArgumentsSlot/Argument and `@EntryPath` becomes EntryPathSlot/EntryPathObject. Source: 2025.1.7 SDK part 05 p916, “ObjectList Data Model Changes.” PlaylistSlot's reference types are Sound, RandomSequenceContainer, SwitchContainer and BlendContainer (same part p628). Applying that wrapper indiscriminately to MusicPlaylistItem would conflate different structures.

Static risk: `skills/waapi-skill/wwise_waapi/operation_registry.py:16744` builds expected list GUIDs as a set; its check near line 16787 compares GUID sets, not ordered sequences. That is useful membership verification but cannot, on its own, certify order-sensitive playback. This is an evidence gap, not a reproduced ordering defect in a supported music workflow.

### Transitions: scalar mutation is not rule-behavior acceptance

MusicTransition's official tables include source/destination object context and context type, destination playlist jump behavior, source exit timing, custom-cue matching, four fade-enable switches, pre-entry/post-exit flags and UseTransitionObject. Sources: 2022.1.19 SDK part 03 pp637–639; 2025.1.7 SDK part 05 pp621–623. Those sources establish a multi-field music rule model, not a complete verified Gateway workflow or all needed nested fade/reference contracts.

Practical risk: individually valid values can still express the wrong exit point, destination, cue match or transition behavior. Acceptance would need the exact intended rule graph and applicable ordering/selection behavior, followed by a bounded playback scenario. No claim is made here that the current code corrupts rules or that WAAPI cannot edit them.

### Stingers: strongest explicit documentation boundary, with a versioned ambiguity

Both official 2022.1.19 SDK part 01 p526 and 2025.1.7 SDK part 01 p560 explicitly advise against creating items in the Stingers list because assigning a Segment through WAAPI is unavailable. This directly corroborates the repository's warning; it is not merely a NotebookLM assertion.

However, the 2025.1.7 MusicStinger table explicitly lists a Segment reference accepting MusicSegment, plus Trigger and scheduling/retrigger properties (SDK part 05 pp603–604). The official example “Setting the trigger of a MusicStinger” edits an **existing** Stinger with object.set (SDK part 02 p75). Thus the sources contain a tension between the creation-limit guidance and later metadata. They do not justify either “all Stinger editing is impossible” or “new Stingers can now be safely created.” Exact live metadata and a disposable creation/association/playback fixture would be needed before relaxing the boundary.

Static guard concern: `_resolve_object_type` at `operation_registry.py:6650` excludes exact normalized `stinger` and `musicsequence` tokens, whereas documented canonical classes include MusicStinger and MusicTrackSequence. The prose therefore should not be treated as proof that every canonical spelling is rejected by that check. Other boundaries may stop a request later; this review did not reproduce a bypass or mutation.

The packaged `resources/metadata/2025.1/object-types.json` specifically records
MusicStinger (classId 2490384) and MusicTrackSequence (classId 3801104) with
`type: WObject`. Those catalog entries do not match either exclusion spelling.
This confirms the static mismatch at that particular check, not a demonstrated
end-to-end mutation or proof that every other guard is ineffective.

## Narrow guard repair

Following the user's request, the creation guard now includes the exact
reflected names MusicStinger, MusicTrackSequence and MusicClipMidi. The last
closes the same spelling-family gap for the existing Clip creation restriction;
it does not prohibit Wwise-generated clips during normal media import.
All five packaged `object-types.json` catalogs supply the actual rows used by
the regression rather than invented metadata labels. The runtime change is
three set entries, retaining the older spelling checks. Existing-object reads
and property/reference edits are not newly prohibited by this creation guard.

The final red regression without those three entries produced 27 failures and
9 passing MusicClip controls across the supported object.create/object.set
lanes. Restoring the entries produced 36/36; object.set 2021 is excluded because
that operation has a separate unavailable-version boundary, not counted as a
pass. Two additional Sound/MusicTrack import controls passed (38 focused
checks). Final wider program results are appended after completion. No live
mutation or Fresh Agent campaign is part of this guard repair.

## Evidence and scope limits

- All SDK paths above are relative to `/Users/xiye/Documents/NotebookLM_Sources/Wwise/Docs/`. Page numbers are one-based physical pages within each PDF part. Text was extracted read-only with PyMuPDF.
- Existing `skills/waapi-skill/references/semantic/2025.1/semantic-builder-object-mutation.md` was used as a lead, not as a substitute for primary pages; it labels its official URLs evidence candidates.
- This bounded review checks 2022.1.19 and 2025.1.7. It does not re-audit all five version lanes or grant Windows, live, Fresh Agent, or audible acceptance.
- Recommended acceptance separation: music media import; playlist tree/order; transition-rule behavior; Stinger segment/trigger/timing. Each needs a small distinct supported workflow or an explicit unsupported boundary.
