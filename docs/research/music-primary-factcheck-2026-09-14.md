# Music CRUD: three disputed NotebookLM claims checked against primary sources

Date: 2026-09-14. Repository context: `c9fbd16` (read-only runtime review; no runtime code changes, Wwise calls, or tests performed for this note).

## Scope and evidence limits

This note checks only (1) Music Track mode versus class identity, (2) Music Clip volume and ownership, and (3) ordinary Switch assignment versus Music Switch assignment. The five user-supplied NotebookLM answers are research leads, not authoritative SDK contracts. Their contradictory claims must not be copied into runtime restrictions or test oracles.

Primary sources are the local official English SDK PDFs under `/Users/xiye/Documents/NotebookLM_Sources/Wwise/Docs/`. Page numbers below are **one-based physical PDF pages within the numbered PDF part**, not pages across the complete SDK book. Text was read with `pypdf`; this is a documentation check, not live property discovery or execution evidence. No older community Q&A was used to establish a cross-version restriction.

## 1. Music Track mode is a property, not a different immutable class

**Conclusion: the claim that Track mode is frozen in the Class ID and changing it requires deleting and recreating the Track is contradicted by all five official object-property tables.**

The documented property is `MusicTrackType`, not `TrackType` or `TrackSequenceType`. All five versions list `int16`, default `0`, with these exact enum values:

- `0`: Normal
- `1`: Random Step
- `2`: Sequence Step
- `3`: Switch

Each MusicTrack reference explicitly directs readers to `ak.wwise.core.object.setProperty` and `setReference` for properties/references; the 2022–2025 references also mention `object.set`. An unknown-property error from supplying `TrackType` would establish a wrong token, **not** an immutable-mode restriction. The correct response is live discovery and the existing property validation boundary, not automatic object destruction/recreation.

| SDK version | Local SDK part | MusicTrack header / property table | MusicTrackType row | MusicTrackSequence reference |
| --- | --- | --- | --- | --- |
| 2021.1.14 | `2021.1.14_en/WwiseSDK-Windows_03.pdf` | p184 | p187 | p191 |
| 2022.1.19 | `2022.1.19_en/WwiseSDK-Windows_03.pdf` | p629 | p632 | p636 |
| 2023.1.19 | `2023.1.19_en/WwiseSDK-Windows_04.pdf` | p250 | p253 | p257 |
| 2024.1.13 | `2024.1.13_en/WwiseSDK-Windows_04.pdf` | p738 | p741 | p745 |
| 2025.1.7 | `2025.1.7_en/WwiseSDK-Windows_05.pdf` | p613 | p616 | p620 |

MusicTrack has Plugin ID `28`, Class ID `1835024`. MusicTrackSequence has Plugin ID `58`, Class ID `3801104`; it is not the alternative class selected when the Track mode becomes Sequence. In the 2022–2025 tables, MusicTrack owns a `Sequences` list accepting MusicTrackSequence, which in turn owns `Clips` accepting MusicClip, MusicClipMidi, and MusicEventCue. Source pages: 2022 p634/p636; 2023 p254/p257; 2024 p742/p745; 2025 p617/p620. The 2021 object reference lists fewer list relationships, so this note does not use absence from that table as proof of unsupported relationships.

This establishes the documented property contract. It does not establish that every transition of mode preserves all populated subtracks without additional Wwise constraints; such a stronger assertion would require a targeted live fixture.

## 2. MusicClip does have Volume; do not conflate three property scopes

**Conclusion: “MusicClip has no Volume” is false in every checked version.** Its SDK property table explicitly lists:

- `Volume`: display name Voice Volume, `Real64`, default `0`, range `[-96.3, 0]`.
- `Is Visible = false`, RTPC type Exclusive, link/unlink support false.

Invisible is a metadata/UI flag, not evidence that the property does not exist. The same class reference directs callers to the WAAPI property APIs. However, this documentation check is not a claim that the current Skill exposes the field, or that a live mutation passed.

MusicTrack also has its own `Volume`, but with range `[-200, 200]`, additive RTPC behavior, and link/unlink support. AudioFileSource's corresponding source gain property is **`VolumeOffset` / Make-Up Gain**, default `0`, range `[-24, +24]`; the reviewed source tables do not contain a plain `Volume` row. In the 2021 reference this source class is titled AudioSource; later references title it AudioFileSource, with the same Plugin ID `0` / Class ID `16`. These are distinct scopes and must not be treated as interchangeable parameters.

| SDK version | Local SDK part | Clip header / Volume | Track Volume | Source full property table / VolumeOffset |
| --- | --- | --- | --- | --- |
| 2021.1.14 | `2021.1.14_en/WwiseSDK-Windows_03.pdf` | p152–153 | p190 | AudioSource p106–108 / p108 |
| 2022.1.19 | `2022.1.19_en/WwiseSDK-Windows_03.pdf` | p595–596 | p635 | AudioFileSource p546–548 / p548 |
| 2023.1.19 | `2023.1.19_en/WwiseSDK-Windows_04.pdf` | p216–217 | p256 | AudioFileSource p165–167 / p167 |
| 2024.1.13 | `2024.1.13_en/WwiseSDK-Windows_04.pdf` | p704–705 | p744 | AudioFileSource p653–655 / p655 |
| 2025.1.7 | `2025.1.7_en/WwiseSDK-Windows_05.pdf` | p579–580 | p619 | AudioFileSource p520–522 / p522 |

The online official [2024.1.6 MusicClip object reference](https://www.audiokinetic.com/ja/public-library/2024.1.6_8842/?id=wwiseobject_musicclip.html&source=SDK), checked on 2026-09-14, independently shows the same Volume row. The exact local 2024.1.13 reference is the version baseline used above.

The tables establish `MusicTrack.Sequences -> MusicTrackSequence.Clips -> MusicClip` for 2022–2025. They do **not**, by themselves, prove the complete audio-import generated graph, automatic Clip creation policy, or a writable `AudioSourceRef`. This note deliberately does not adopt the NotebookLM “standalone Clip creation always fails” claim or its proposed creation workaround. Those need the separate object import documentation and, if needed, a minimal disposable fixture.

## 3. Ordinary Switch assignment is not established as a Music Switch operation

**Conclusion: reject the NotebookLM recommendation to use `ak.wwise.core.switchContainer.addAssignment` for MusicSwitchContainer as unproven.**

All five official function descriptions say the operation assigns a child of a **Switch Container** to a Switch/State, equivalent to drag-and-drop into the **Assigned Objects** view. The arguments must identify a child of that container and a State/Switch from the group currently selected on that container. They do not name MusicSwitchContainer or describe its multi-group path entries.

| SDK version | Local SDK function reference | Physical page |
| --- | --- | --- |
| 2021.1.14 | `2021.1.14_en/WwiseSDK-Windows_02.pdf` | p374 |
| 2022.1.19 | `2022.1.19_en/WwiseSDK-Windows_02.pdf` | p686 |
| 2023.1.19 | `2023.1.19_en/WwiseSDK-Windows_03.pdf` | p91 |
| 2024.1.13 | `2024.1.13_en/WwiseSDK-Windows_03.pdf` | p247 |
| 2025.1.7 | `2025.1.7_en/WwiseSDK-Windows_03.pdf` | p547 |

The official [2024.1.8 assignment example](https://www.audiokinetic.com/library/2024.1.8_8898/?id=ak_wwise_core_switchcontainer_addassignment_example_assigning_a_switch_container_s_child_to_a_state.html&source=SDK) likewise describes the Assigned Objects view, not Music Switch paths.

MusicSwitchContainer has a different documented structure:

- 2023.1.19 `SDK_04` p242–243: `Arguments` list accepts SwitchGroup or StateGroup; `Entries` accepts MultiSwitchEntry.
- 2024.1.13 `SDK_04` p730–731: the same listed types.
- 2025.1.7 `SDK_05` p605–606: `Arguments` instead accepts MusicArgumentsSlot; `Entries` still accepts MultiSwitchEntry.
- The 2021.1.14 MusicSwitchContainer reference begins at `SDK_03` p176; 2022.1.19 begins at `SDK_03` p620. These older tables do not supply the same Arguments/Entries declarations at their expected alphabetical positions; this is not proof of native inability and cannot justify copying the later shape backward.

Therefore a Music Switch editor must be designed from its own version-specific Arguments/Entries contract, not by relabeling the existing ordinary Switch-assignment tool. **No native call was issued to prove addAssignment rejects MusicSwitchContainer**, so the result here is a documented scope distinction and lack of support evidence, not a new five-version runtime failure claim.

## Consequences for the release repair

1. Keep the current narrow Music Track import/default-value repair separate from a complete interactive-music editor.
2. Do not add destructive Track recreation as a workaround for an invented property token.
3. Keep field identity and validation bound to exact object/class scope. Track Volume, Clip Volume, and source VolumeOffset must not share an unchecked universal mapping.
4. Do not exclude a property solely because its documented visibility is false; inspect the actual Gateway discovery policy and live metadata before making an exposure decision.
5. Do not add MusicSwitchContainer to ordinary Switch assignment based on the NotebookLM answers. The music Arguments schema also has a demonstrated 2025-versus-2023/2024 difference that requires version-aware handling if this capability is implemented.

This note provides primary-source corrections and boundaries, not executable acceptance credit. It does not update test inventories or declare a new supported music workflow.
