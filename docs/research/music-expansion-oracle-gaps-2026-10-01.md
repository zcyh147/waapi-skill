# Music expansion: complete fixture extraction and remaining oracle proof

Date: 2026-10-01. Bounded primary-source follow-up for #120/#121 under #108. This document records read-only XML, installed official Help, and current public-contract evidence. No project edit, Gateway execution, Wwise launch, test, Fresh campaign, or implementation occurred. Existing scalar PASS evidence remains attached to its original candidate; this research creates no execution credit.

## Sources and reproducibility

The committed music baselines are [2022 Music.wwu](../../tests/_org/2022.1/Interactive%20Music%20Hierarchy/Music.wwu) (previously recorded SHA-256 `88d38034004bd745fb2248784cc93bc9ed8d1cd1dc9dc3468c1312e167a9b0f9`) and [2025 Music.wwu](../../tests/_org/2025.1/Containers/Music/Music.wwu) (`5b92968638cf618eeedcdc6213df683e58e32ec332e34fdda9f584912566136b`). Extraction selected objects by exact GUID and their direct XML owner/collection nodes; descendant traversal was not used to mix nested owners' collections. State membership comes from each lane's `tests/_org/<version>/States/Music.wwu`.

Installed metadata is first-party version-specific source, not live discovery: [2022 WObjects.xml](</Library/Application Support/Audiokinetic/Wwise 2022.1.19.8584/Authoring/Data/WObjects/WObjects.xml>) (`018ddcb9e0b50c4cdc2f0849d0cc8a95d5568c169f0c888ca6f07c3f0e3266b6`) and [2025 WObjects.xml](</Library/Application Support/Audiokinetic/Wwise 2025.1.7.9143/Authoring/Data/WObjects/WObjects.xml>) (`3b363c24b7ffa032d7efc12f36023cd944b8f53323af33fcbe738c2193918454`).

Online exact-build Help URLs were attempted through both Audiokinetic library forms but unavailable to the browsing tool. The installed official English Help archives supplied the version-matched content instead. `7z x -so` read members to stdout only; no extracted files were saved.

| Official archive | Archive SHA-256 | Member / member SHA-256 |
| --- | --- | --- |
| [2022.1.19.8584 WwiseHelp_en.chm](</Library/Application Support/Audiokinetic/Wwise 2022.1.19.8584/Authoring/Help/WwiseHelp_en.chm>) | `39a2b9f1f7190ca2dbde6a953ee8776c0e8cbc37a8e5007eec3ddde47379f0f1` | Music Fade Editor: `ch59s02s04s08s04.html` / `1d3d879786504f4969d5a1a01268f54b9b3572b0495156ac5ce708841855aa39`; Music Switch Container Association Editor: `ch59s02s04s08s01.html` / `4345df57f40eef806eff1f864c3dd568f78661eaf112d5e751cdb3e9c2c1d17c` |
| [2025.1.7.9143 WwiseHelp_en.chm](</Library/Application Support/Audiokinetic/Wwise 2025.1.7.9143/Authoring/Help/WwiseHelp_en.chm>) | `2c17662af99cdc7476b2dee1c3e1274a9df8b9e98550197d68e8d25a543491db` | Music Fade Editor: `ch61s01s04s08s04.html` / `039f87aa7bc12d1478e8a870c7733a5423a6e05b851580b718889fc55c2a4ebf`; Music Switch Container Association Editor: `ch61s01s04s08s01.html` / `6316409ce36b139698bd4943d71efb1c1eb722d068de6dcdb6a80964787c85e3` |

## Music Switch: complete two-dimensional baseline

The selected owner is `02_In-Game Music`, `{A9D070F3-3BD9-49EB-9D8B-5D3312173FB4}`. Both lanes serialize the same two ordered groups and nine mappings. Source collection anchors: [2022 ArgumentList/EntryList](../../tests/_org/2022.1/Interactive%20Music%20Hierarchy/Music.wwu#L16621), [2025 Arguments/Entries](../../tests/_org/2025.1/Containers/Music/Music.wwu#L15490). This is XML baseline order, not a claim that WAAPI row order or list order determines runtime priority.

| Condition identity | Exact GUID | Group membership |
| --- | --- | --- |
| Music_Global group | `{6BC46605-3653-483C-AE48-FC0ACD9A2951}` | Dimension 1 |
| InGame | `{7C400264-0402-4E47-930D-960FBDD8605B}` | Music_Global |
| Menu state | `{9B0A4623-43A8-4367-A0C4-FB5C0B920B6C}` | Music_Global |
| Music_Global's None | `{7993CD7C-BBA7-4A63-9E5A-4003C1B86F3C}` | Music_Global; not used by the nine tuples |
| Music_inGame group | `{AF599241-DE64-4286-BB8B-B0260EE20B80}` | Dimension 2 |
| None | `{4BA09D62-D59B-4880-A78C-8BECE7D7899F}` | Music_inGame |
| a_Stealth | `{43C6702F-3A30-4D5C-B16D-C862BE5989EF}` | Music_inGame |
| b_Stress | `{885FDC4C-AE0A-4B71-A9FB-82FBAE4A3270}` | Music_inGame |
| c_Fight | `{20A3B196-D22F-42F7-8592-A37A3E5B467A}` | Music_inGame |

Membership sources: [2022 States/Music](../../tests/_org/2022.1/States/Music.wwu#L6), [2025 States/Music](../../tests/_org/2025.1/States/Music.wwu#L6). The two None GUIDs are distinct.

Target aliases in the next table mean exactly: Stealth `{20FA9A69-7ECC-4B05-BD6B-2C9527CD88C2}`, Fight `{1D0ECA1F-2749-4DBB-B92C-0DBDFDA7A825}`, Stress `{52B9FAC3-636E-44F8-9015-E5F24E30E39E}`, Menu `{7286E840-F743-4D12-9647-C695B244B573}`. The Stealth target here differs from the first container's Stealth Playlist `{492A2BCA-08ED-4ED9-BDA3-B4D876D2D830}`.

| Baseline position | Ordered tuple (dimension 1, dimension 2) | Target | 2025 entry GUID |
| --- | --- | --- | --- |
| 1 | Music_Global group, Music_inGame group | Stealth | `{BB6519A2-1173-4569-B1F6-57305FEBB759}` |
| 2 | InGame, None | Stealth | `{903A30EC-F1F4-49FF-9CBC-99B89539598B}` |
| 3 | InGame, c_Fight | Fight | `{7AE5D86A-30A6-4AC9-A909-C57953EE03BE}` |
| 4 | InGame, b_Stress | Stress | `{4F98CAE7-F96A-4C18-8733-15A31CF40AC1}` |
| 5 | InGame, a_Stealth | Stealth | `{8158C5B6-73BB-4B5D-B02D-C7FD6A642A49}` |
| 6 | Music_Global group, c_Fight | Fight | `{8CA7ACF4-E9F8-4F67-9FCE-FC12E323BEAC}` |
| 7 | Music_Global group, b_Stress | Stress | `{C8085861-F375-48ED-94FB-AA4B39DB8B64}` |
| 8 | Music_Global group, a_Stealth | Stealth | `{F66C5F2D-E01E-43CD-BE5A-16F5F20E97A6}` |
| 9 | Menu state, Music_inGame group | Menu | `{1F7BC8C1-AEC9-40B7-BBA2-1FE12C4B346F}` |

2022 node identities are `ArgumentList/ArgumentRef`, `EntryList/Entry/Path/PathElementRef`, and `Entry/AudioNodeInfo/AudioNodeRef`. Entries lack the 2025 entry GUID attributes, so the complete ordered tuple is their baseline comparison identity.

2025 node relationships are `ObjectLists/ObjectList[@Name='Arguments']/PluginInnerObject` (MusicArgumentsSlot) → `ReferenceList/Reference[@Name='Argument']/ObjectRef`; `ObjectList[@Name='Entries']/MultiSwitchEntry` → `Reference[@Name='AudioNode']/ObjectRef`; and each entry's `ObjectList[@Name='EntryPath']/PluginInnerObject` (EntryPathSlot) → `Reference[@Name='EntryPathObject']/ObjectRef`. The two argument-slot GUIDs, in order, are `{147D74E6-BCCD-4F41-80F9-EAE3ABF79D0A}`, `{56D7643F-6929-4007-9F41-7AB76D9EAB44}`.

| Entry position above | Ordered 2025 EntryPath slot GUIDs |
| --- | --- |
| 1 | `{689F1644-6813-44ED-8DCA-F2A068057A59}`, `{4ACFB80A-D33E-4A67-8538-34B8ED3BA04C}` |
| 2 | `{248252BE-ACBD-44B7-B53E-0C4F64185B8C}`, `{A5968004-9453-467D-8E30-F3A37456B17D}` |
| 3 | `{4BD69BB5-AB87-4107-850B-557C35B60FF8}`, `{6AF88A29-0333-4641-9860-6DD3502A202E}` |
| 4 | `{1B1145C4-E0D9-4A7B-98D0-1CA7CC6B91AF}`, `{E5A227CF-5D71-4851-93C3-B04052B96915}` |
| 5 | `{E3F94263-12D1-4BF4-8796-1ACA46A1E391}`, `{45DCA63B-32B0-48E7-A3C9-068526605547}` |
| 6 | `{65A8468A-348F-40C7-90A1-0617420007DA}`, `{5B539F01-8A59-4FC4-B314-501F853C7A78}` |
| 7 | `{9EC6227B-CC5F-4057-9380-2D5BF6E6F598}`, `{C0381501-04E9-4B75-99AF-5667D938F6BF}` |
| 8 | `{7CA7CB4E-042E-4624-8352-4AA60D1D78E1}`, `{31AF0C4C-4C05-49CD-9105-BEF802436FCA}` |
| 9 | `{62491AE5-B74F-4894-AB13-B8DD40FF4F99}`, `{A3D67A6B-6B63-4E02-81AF-CF3685ECAF68}` |

Official installed [2025 metadata](</Library/Application Support/Audiokinetic/Wwise 2025.1.7.9143/Authoring/Data/WObjects/WObjects.xml:1434>) declares AudioNode, EntryPath/EntryPathObject; its [MusicSwitchContainer definition](</Library/Application Support/Audiokinetic/Wwise 2025.1.7.9143/Authoring/Data/WObjects/WObjects.xml:6435>) declares Arguments/Argument and Entries. It permits StateGroup/SwitchGroup argument references and group/value EntryPathObject references. This explains the wrapper structure but does not prove live field-handle binding or complete maintenance.

### Group-valued paths and wildcard semantics

Both installed Association Editor Help members define `*` as matching any corresponding State/Switch. They document Best Match selection and a Weighted alternative. They do **not** specify the XML/WAAPI encoding of that wildcard as a group GUID. The [historical 2025 live read projection](music-capability-probe-results-2026-09-28.json), record `36aed1113faaea69309cda0e08f178261093467853606490d8a1215b5a50328d`, displayed the group/group entry as `[*.* (MultiSwitchEntry)]` and group/value entries with `*` in the corresponding position. This is observed correlation on that build; it is not a pinned native serialization contract. Preserve exact group GUIDs and the Match Mode setting. The group-GUID→wildcard encoding and effective priority semantics remain unproven for a public configuration compiler; no playback claim is needed here.

### Complete preservation oracle

For the proposed existing `(InGame, None)` retarget, require exactly the nine tuples above, ordered group identities, width 2, correct value membership, exact entry/slot ownership, and only position 2's AudioNode change to Fight. Preserve the other eight targets, group-valued paths, all stable entry/slot GUIDs, ordering where independently authoritative, Probability/Weight, Match Mode, ContinuePlay, owner references/properties, and every referenced music object's contents. Reject swapped dimensions, duplicate/omitted/extra tuples, or an unordered collection of condition GUIDs without target association. Explicit and metadata-default values must be compared without silently rewriting defaults.

## Transition: actual existing-rule and fade baselines

The historical maintenance target `{B24173D4-7534-4C19-ACE0-F1F1B0EBD535}` sits under root `{2069AEE0-7C62-4F57-B7AA-D7325D150A39}` owned by Stealth `{492A2BCA-08ED-4ED9-BDA3-B4D876D2D830}`. In [2022](../../tests/_org/2022.1/Interactive%20Music%20Hierarchy/Music.wwu#L1569) ownership is `TransitionList/MusicTransition/ChildrenList`; in [2025](../../tests/_org/2025.1/Containers/Music/Music.wwu#L322), `ReferenceList/Reference[@Name='TransitionRoot']/Custom/MusicTransition/ChildrenList`. Both contain exactly one rule, explicit true PlayDestinationPreEntry/PlaySourcePostExit, and empty TransitionInfo. No serialized fade exists. Thus the existing post-exit boolean PASS proves neither fade maintenance nor preservation of a nontrivial sibling-rule list.

An alternative existing target with an actual saved fade and sibling rules exists under the selected `02_In-Game Music` owner. Its root is `{8A6F5BFD-8784-474D-8BDE-6460595AA1FC}`; first rule `{E49EF1AA-29FB-40F1-B343-523AF28244AE}` owns `TransitionInfo/SourceFadeOut/MusicFade` `{0FC1E836-74BB-43AB-B417-6C9D16AE5636}`. Sources: [2022 rule/fade](../../tests/_org/2022.1/Interactive%20Music%20Hierarchy/Music.wwu#L16133), [2025 rule/fade](../../tests/_org/2025.1/Containers/Music/Music.wwu#L7242). The first rule explicitly enables source fade-out; its saved fade fields are FadeCurve, FadeOffset, FadeTime, FadeType. This evidence supports an existing-fade investigation rather than assuming fade creation on the historical target.

Both root ChildrenLists have this exact 15-rule order:

1. `{E49EF1AA-29FB-40F1-B343-523AF28244AE}`
2. `{1071725D-F3B3-403E-BFB7-A8F55D8F70C5}`
3. `{3ADBBB01-3C00-48E9-8B98-48EB1D8888D6}`
4. `{1D05C665-49A1-4FF6-BB62-90CECE479B96}`
5. `{234C3AE1-5CA6-44BF-B40F-1D7D970A4E4A}`
6. `{918A0CC3-7E52-47B9-A641-1ED9C40CACA3}`
7. `{B5832EB2-BACE-4088-AB24-CFDA16884DC8}`
8. `{316B82BA-298C-4194-A58D-A2563C39C3AA}`
9. `{30D287DE-8BC3-486B-9100-661B7A568EDB}`
10. `{841109D9-8052-41F7-B5FF-837E1F62459E}`
11. `{9A8C59CF-4F03-4D76-9BBB-0540E7A8AB97}`
12. `{F6203BF7-5059-44B7-867F-B98C372FC64F}`
13. `{BE1D5071-F444-40F1-9499-9327F5B8BC0C}`
14. `{11E1CBC0-C4A6-4F1A-880E-256861D9F477}`
15. `{6F215F6B-324E-49F1-924F-055237372C7C}`

Preserve all fourteen nonselected rule subtrees, their order, root/owner identity, other transition/fade objects, context references, transition-object/jump-to references, and the owner's music contents. For the selected rule, require complete context/timing/pre-post/fade readback; correct fade GUID alone is not role proof.

### Versioned enum meanings and units

Both installed [2022 Transition metadata](</Library/Application Support/Audiokinetic/Wwise 2022.1.19.8584/Authoring/Data/WObjects/WObjects.xml:2519>) and [2025 Transition metadata](</Library/Application Support/Audiokinetic/Wwise 2025.1.7.9143/Authoring/Data/WObjects/WObjects.xml:2494>) declare these labels. Caller values must be resolved from matching live metadata; native integers are deliberately not supplied here.

| Token | Declared labels / meaning |
| --- | --- |
| SourceContextType, DestinationContextType | Any, Nothing, Object |
| SourceContextObject, DestinationContextObject | Source/Destination Object references; 2022 restricts InteractiveMusic category, 2025 enumerates MusicSegment, MusicPlaylistContainer, MusicSwitchContainer, Folder |
| ExitSourceAt | Immediate, Next Grid, Next Bar, Next Beat, Next Cue, Custom Cue, Exit Cue, Never (only for music tracks) |
| ExitSourceCustomCueMatchName | Enabled for Next Cue/Custom Cue; not an unconditional writable cue field |
| DestinationJumpPositionPreset | Entry Cue, Same Time as Playing Segment, Random Cue, Random Custom Cue, Last Exit Position |
| DestinationPlaylistJumpTo | Start of Playlist, Specific Playlist Item, Last Played Segment, Next Segment |
| FadeType | Fade-in, Fade-out |
| FadeCurve | Logarithmic (Base 3), Sine, Logarithmic (Base 1.41), Inverted S-Curve, Linear, S-Curve, Exponential (Base 1.41), Reciprocal Sine, Exponential (Base 3) |

The first alternative rule explicitly saves ExitSourceAt corresponding to Immediate and EnableSourceFadeOut true. Its fade saves the metadata-declared S-Curve, fade-out type, and numeric FadeTime/FadeOffset values of 6. Missing source/destination context properties are not explicit Any writes; installed metadata declares Any defaults. Missing live/default values must still be read, not manufactured from XML absence.

Both official installed **Music Fade Editor Help** members label Time and Offset as seconds: Time is duration, range 0–60; Offset is relative to the relevant cue, range −60–60. For source fade-out it relates the end of the fade to the exit cue; for destination fade-in it relates the start to the entry cue, as the official editing-fades instructions explain. [Official online editing instructions](https://www.audiokinetic.com/en/library/edge/?id=setting_source_and_destination_properties&source=Help) were retrieved but are unpinned corroboration, not 2022/2025 native-contract evidence.

**Native-value conversion remains unknown.** The installed [2022 MusicFade metadata](</Library/Application Support/Audiokinetic/Wwise 2022.1.19.8584/Authoring/Data/WObjects/WObjects.xml:2731>) and [2025 MusicFade metadata](</Library/Application Support/Audiokinetic/Wwise 2025.1.7.9143/Authoring/Data/WObjects/WObjects.xml:2712>) declare Real64 fields, defaults and ranges consistent with the UI, but no explicit WAAPI/storage conversion factor. The saved value 6 is not independent proof that WAAPI takes seconds. No matching primary source reviewed here establishes whether public WAAPI property values are identical to UI seconds. Do not apply Action milliseconds, SDK SoundEngine transition milliseconds, or an assumed factor of 1000. A setter's success and identical raw readback alone would prove round-trip storage, not the requested physical unit.

## Current public contract versus remaining live proof

The public [Gateway](../../skills/waapi-skill/scripts/gateway.py#L727) exposes children/parent/ancestors/descendants/references-to relationships, not a dedicated fade-role, Music Switch tuple, or ordered collection business read. Exact-ID `query-object --include-field <meaning>` owns live property/reference meaning resolution; it cannot combine that option with relationship traversal. Existing [draft-declare-field-change](../../skills/waapi-skill/scripts/gateway.py#L2898) takes bound object/field handles and either a business value or target handle. A successful generic reference route does not provide a complete tuple compiler or aggregate preservation oracle.

When the closed query cannot express a required collection read, `query-schema --advanced` discloses the bounded read-only object.get contract. The [existing maintenance probe](../../tests/maintenance/probe_music_expansion_capabilities.py#L114) already uses that path for @Arguments/@Entries. Historical 2025 complete collection identities passed; 2022 those native accessors returned unknown-property errors. They do not prove that all alternative earlier-version native access is impossible. The public [object graph compiler](../../skills/waapi-skill/wwise_waapi/object_graph_business.py#L1278) rejects nested object-list declarations; [2025 canonical semantic evidence](../../skills/waapi-skill/references/semantic/2025.1/discrepancy-register.md#L13) describes slot wrapping, but does not authorize caller-native list payloads. Ordinary switchContainer assignment is not a replacement for the two-dimensional Music Switch outcome.

### Minimal bounded probe plan for the root coordinator

1. Use one existing lifecycle-owned SampleProject copy per lane, sequentially, with exact host/build/project, source full hash/mtime, and cleanup proof. Keep independent before/after read receipts and immutable Preview artifacts. This plan does not start execution.
2. Music Switch 2025: repeat only the needed complete @Arguments/@Entries reads through the disclosed advanced contract (fixed cap 16). Exact-ID query the two known argument slots with field meaning Argument; the nine entries with Audio Node, Probability, Weight; read each EntryPath collection with cap 4; exact-ID query the eighteen returned slots with EntryPath Object. Compare all references to the tables above and establish group membership through exact group children reads. Treat unknown, duplicate, truncated, or wrong-owner results as a boundary. Query order is not automatically authoritative: corroborate saved owned XML after a separately authorized save where necessary.
3. Music Switch 2022: retain the known @Arguments/@Entries rejection. Inspect version-disclosed public schema and live metadata for the owner/entry representation before any alternative bounded read. Do not guess replacement accessors from XML names. If the complete tuple cannot be retrieved through the packaged route, report that exact public read/oracle gap; no implementation is implied.
4. Transition both lanes: exact-ID query the alternative root, all fifteen rules, and existing fade; discover Source Type, Destination Type, Source Object, Destination Object, Exit Source At, Destination Sync To, Play Source Post-exit, Play Destination Pre-entry, Enable Source Fade-out and the three fade value fields. Use the returned enum labels, enabled states, reference restrictions, and units if disclosed. Test public children/parent relationships against the saved owner/role; lack of such traversal is not repaired by a display-path selector or guessed native reference.
5. Before a physical-duration mutation, obtain matching primary unit documentation or compare a known UI/independently attested setting with exact public readback and saved-sandbox values. Merely seeing numeric 6 at both storage locations cannot establish seconds. If unit authority remains absent, leave duration/offset acceptance blocked while reporting successful field disclosure separately.
6. Only after the complete oracle and units are closed, prepare the full existing-rule maintenance request or selected Music Switch retarget through the current field-handle seam. If enabled-state dependencies require successive transactions, disclose the ordered sequence; each has its own immutable approved Preview, durable authorization, at-most-once execution and verification. Check complete preservation above, without playback. A missing public seam gets a separately agreed scope; do not reduce the full task to a boolean or collection-existence probe.

This leaves concrete research boundaries rather than invented API shapes: authoritative collection order, 2022 complete Music Switch readback, live wrapper/fade binding and role traversal, live field enabled-state restrictions, and native physical-time units/conversion. No claim that a new music feature is implemented or an investigation ticket is closed is made here.
