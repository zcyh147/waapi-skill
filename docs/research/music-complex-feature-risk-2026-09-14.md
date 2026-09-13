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

At exact repair candidate `6d3ce68dd6f442ad307172e6caa5fc095d7cd2dd`, the
four focused Registry/import test files passed **651 tests**; the fixed Program
gate passed **5302 tests, 2 Windows-only skips**, exit 0, 260.89 seconds.
HEAD and source status remained unchanged through the gate, and no scoped
test process remained. No full Non-live rerun was needed for three guard
entries; the preceding broad-run accounting remains preserved separately.

### Installed WObjects.xml cross-check

The user supplied the Windows source location
`C:\Audiokinetic\Wwise2021.1.14.8108\Authoring\Data\WObjects\WObjects.xml`.
On this Mac the corresponding installation payload is under
`/Library/Application Support/Audiokinetic/Wwise <build>/Authoring/Data/WObjects/WObjects.xml`,
not directly inside the app executable bundle. The Wine Program Files entries
point to this location. Read only `WwiseObject Name` as a concrete class, not
the shared `ObjectBase` definition names.

All five installed builds list MusicStinger, MusicTrackSequence, MusicClipMidi
and MusicPlaylistContainer under those exact names. In order, the physical XML
lines are:

| Build | Stinger | Track Sequence | MIDI Clip | Playlist Container |
| --- | --- | --- | --- | --- |
| 2021.1.14.8108 | 2790 | 6201 | 3653 | 6110 |
| 2022.1.19.8584 | 2810 | 6286 | 3673 | 6195 |
| 2023.1.19.8928 | 2747 | 6152 | 3616 | 6053 |
| 2024.1.13.9056 | 2715 | 6168 | 3610 | 6051 |
| 2025.1.7.9143 | 2791 | 6544 | 3686 | 6420 |

The XML is an offline type-definition baseline, not proof that every class is
publicly creatable or that every API uses an identical wire token.

## Three parallel visible-task smoke checks

The user requested three quick parallel conversations in `waapi_skill_test`.
They used Sol / High, the demonstration Skill copy with the guard fix, and the
already-running Authoring 2025.1. Scope was explicitly read-only discovery and
Preview only: no confirmation, execute, playback, project/config/code changes
or fixture creation. These are visible app tasks, not the formal Fresh CLI
campaign; no formal memory-isolation credit is claimed.

| Task | Final observed result after at most one guided correction |
| --- | --- |
| Playlist `01a09c0c-e56f-7ed3-aef8-9f507c9acce9` | Existing Segments and their MusicPlaylistContainer parent were found and exactly re-read. `draft-discover-fields` failed with `OBJECT_TYPE_NOT_UNIQUE`: requested MusicRanSeqCntr, zero matches. No Preview. |
| Transition `01a09c0c-de84-79c1-a6d8-7eb4b6c135d8` | Closed `music-playlist-container` query compiled MusicRanSeqCntr; Wwise rejected it with `WaapiRequestFailed` / `ak.wwise.query.invalid_query`, Unknown object type. Did not reach transition authoring. No Preview. |
| Stinger `01a09c0c-e923-7e70-a6ca-8aa81766ce4e` | Existing Stingers, Triggers and Segments were found. Binding an existing MusicStinger with a live empty name failed `BUSINESS_OBJECT_BINDING_MISMATCH`. Did not reach changing Trigger or prove the new-Stinger boundary. No Preview. |

The first Playlist/Stinger attempts stopped on tool-output truncation after a
91-Segment query. One guided retry reduced the result bound to two. The first
Transition attempt incorrectly jumped to advanced WAQL and invented a brace
syntax; the one guided retry used the closed query layer and exposed the
different, deterministic type-mapping error. Preserve these first failures;
the guided turns are not first-attempt PASS evidence. None of the three checks
is music workflow acceptance, and no user-project mutation occurred.

Read-only triage identified `business_declarations.py`'s shared
music-playlist-container definition mapping both native and metadata types to
MusicRanSeqCntr. Query compilation and field discovery consume those fields;
the five packaged catalogs and installed XML instead name MusicPlaylistContainer.
The import metadata alias in `operation_registry.py` also deserves examination.
Native creation/import tokens must be independently verified rather than
blindly globally replaced. The Stinger empty-name binding failure is a separate
identity-handling issue. Neither newly discovered issue was patched as part
of the three-entry creation-guard repair.

## Follow-up: shared type and identity fixes

The subsequent repair separates three concrete defects from the complex-feature
support boundary:

- The closed Playlist kind, create/import parent guards, and import metadata
  resolver now use the reflected `MusicPlaylistContainer`. Native import syntax
  aliases are retained only in their own resolver, not substituted globally.
- Import metadata for `PropertyContainer` now resolves to `PropertyContainer`
  in 2025.1 and `ActorMixer` in older lanes, rather than incorrectly using
  `Folder`. A five-version audit of all twelve semantic kinds found no other
  missing metadata type names.
- The Stinger binding failure was not caused by its empty name, which was
  already supported. Its live path was the derived display identity
  `[Stinger : Bonus,Stinger Bonus - Fight]`. Reviewed non-intrinsic types can
  now preserve a bounded bracketed display identity while continuing to bind
  and revalidate by exact GUID. Display text is never a query selector;
  malformed identities and changes between preparation phases still fail.

Development regression evidence: the type-mapping tests reproduced 12 failures
before the fix and then passed 83 selected checks. The derived-identity file
passed 119 checks; the four-file identity/business regression passed 393 checks.
A new sandbox test passed on 2025.1, proving closed Playlist query, creation,
and use as the parent of a structure-only MusicSegment import. This does not
prove PlaylistRoot entries/order, transition behavior, or playback. Frozen
candidate gates and the visible-task follow-up are recorded separately below.

## Evidence and scope limits

- All SDK paths above are relative to `/Users/xiye/Documents/NotebookLM_Sources/Wwise/Docs/`. Page numbers are one-based physical pages within each PDF part. Text was extracted read-only with PyMuPDF.
- Existing `skills/waapi-skill/references/semantic/2025.1/semantic-builder-object-mutation.md` was used as a lead, not as a substitute for primary pages; it labels its official URLs evidence candidates.
- This bounded review checks 2022.1.19 and 2025.1.7. It does not re-audit all five version lanes or grant Windows, live, Fresh Agent, or audible acceptance.
- Recommended acceptance separation: music media import; playlist tree/order; transition-rule behavior; Stinger segment/trigger/timing. Each needs a small distinct supported workflow or an explicit unsupported boundary.
