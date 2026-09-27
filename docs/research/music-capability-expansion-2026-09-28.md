# Music capability expansion: Playlist, existing Transition, Music Switch

Date: 2026-09-28. Research for #119, #120, and #121 under #108.
Read-only code/resource/installed-metadata/SampleProject inspection; no live
WAAPI call, test, Wwise process, XML edit, runtime edit, or new execution credit.
HEAD observed near completion: `70298fa317cd363c2f526bb6a762920e2baf31ba`.
Other work continued concurrently; the concrete source locations below, not
an assertion that the entire worktree was frozen, identify this inspection.

## Decision

Start with existing-object probes through the current public field-handle
interface. Do not add a new music DSL before these cheaper probes establish
which part actually needs extension.

| Scope | Current public expression | Readback position | Verdict before live probe |
| --- | --- | --- | --- |
| Existing Playlist item loop/mode property | `object.setProperty`, or existing `object.set` row with a discovered field handle | Exact-ID `query-object --include-field` can request live-discovered scalar fields | Plausible current path in both lanes; live field enabled-state and derived identity must pass |
| Existing Playlist item Segment reference | `object.setReference` if live discovery exposes Segment | 2025 installed metadata exposes Segment; 2022 installed metadata does not | Probe 2025 first; 2022 disclosure boundary is likely, not proof native WAAPI cannot do it |
| New PlaylistRoot/recursive items, ordered A→B→A | No complete current business declaration for reference-owned new root plus recursive anonymous item placement/order | Generic list verifier compares GUID sets, not playback sequence | Public construction/oracle gap; ordinary container creation is insufficient |
| Existing Transition scalar/context-reference edit | Existing property/reference handles, with exact live object identity | Existing rule fields have concrete metadata in both versions | Probe current path first; new rule creation and complete scheduling/fades are separate |
| Existing MusicFade scalar edit | Potential ordinary property handle on the actual MusicFade object | Must identify the correct fade object/role; not merely an enable flag on Transition | Conditional; no parent-level FadeTime shortcut and no scheduling claim |
| Existing 2025 MultiSwitchEntry AudioNode target | `object.setReference` after exact entry/target binding | Installed metadata exposes AudioNode; query can discover it | Plausible small current path, conditional on independent complete path preservation |
| Existing/new complete Music Switch multi-dimensional paths | No proven closed path-outcome compiler; current nested-list declaration is explicitly rejected | 2025 has Arguments/EntryPath slots; 2022 WWU uses dedicated ArgumentList/EntryList | Versioned business seam and ordered-tuple oracle needed unless the sandbox probe establishes a narrower supported existing-field route |

These are expression and evidence judgments, not completed live results.
An unexposed reference is not the same as prohibited native creation. A
discoverable type is not a supported placement or a verified playback feature.

## Source authority and reproducibility

The packaged canonical semantic references were used to locate relevant
concepts and boundaries: [2022 object mutation](../../skills/waapi-skill/references/semantic/2022.1/semantic-builder-object-mutation.md),
[2025 object mutation](../../skills/waapi-skill/references/semantic/2025.1/semantic-builder-object-mutation.md),
and the matching property/reference and query notes in those directories.
Their URL status is explicitly `evidence-candidate`; their prose is not a
substitute for a current public contract or live metadata.

Primary offline facts below come from the installed Audiokinetic
`Authoring/Data/WObjects/WObjects.xml` and committed SampleProject WWUs.
Their XML representation is evidence to inspect, never an editing interface
or an authorization to synthesize a WAAPI mutation payload.

| File | SHA-256 read in this audit |
| --- | --- |
| `tests/_org/2022.1/Interactive Music Hierarchy/Music.wwu` | `88d38034004bd745fb2248784cc93bc9ed8d1cd1dc9dc3468c1312e167a9b0f9` |
| `tests/_org/2025.1/Containers/Music/Music.wwu` | `5b92968638cf618eeedcdc6213df683e58e32ec332e34fdda9f584912566136b` |
| `/Library/Application Support/Audiokinetic/Wwise 2022.1.19.8584/Authoring/Data/WObjects/WObjects.xml` | `018ddcb9e0b50c4cdc2f0849d0cc8a95d5568c169f0c888ca6f07c3f0e3266b6` |
| `/Library/Application Support/Audiokinetic/Wwise 2025.1.7.9143/Authoring/Data/WObjects/WObjects.xml` | `3b363c24b7ffa032d7efc12f36023cd944b8f53323af33fcbe738c2193918454` |

Installed 2025.1.11 was present but not used for these metadata comparisons.
The real probe must record its actual build and re-discover all fields; do not
silently label 2025.1.7 offline facts as 2025.1.11 live evidence.

## Concrete fixture anchors

The following identities are read from the committed 2022 and 2025 files.
Use them only after the lifecycle has copied the matching project to an owned
sandbox, opened that copy, and the Gateway has attested the expected project.

| Role | GUID / expected relation |
| --- | --- |
| Stealth MusicPlaylistContainer | `{492A2BCA-08ED-4ED9-BDA3-B4D876D2D830}` |
| Stealth Playlist root item | `{15F37D81-B510-4B20-8B71-CDAADA2820BE}` |
| First Playlist item | `{DE090E27-2F5C-436F-A239-D02F8D5016B2}` → Stealth_Seg_01 `{EBAFEE65-F685-49C0-9171-F2ECB0D3D3A8}` |
| Second Playlist item | `{074B5844-847D-44B6-84AC-5F9C4D178899}` → Stealth_Seg_02 `{EEEBE468-8537-4BFC-812F-35B49B38B326}` |
| Third Playlist item | `{898C3D43-E6A9-4327-8029-61E657048399}` → Stealth_Seg_03 `{72A6F367-3EFB-48BC-8960-D6CE02F26114}` |
| Existing Stealth Transition rule | `{B24173D4-7534-4C19-ACE0-F1F1B0EBD535}`; serialized PlayDestinationPreEntry and PlaySourcePostExit are true in both fixtures |
| Two-dimensional MusicSwitchContainer | `02_In-Game Music`, `{A9D070F3-3BD9-49EB-9D8B-5D3312173FB4}` |
| Ordered argument groups | Music_Global `{6BC46605-3653-483C-AE48-FC0ACD9A2951}`, then Music_inGame `{AF599241-DE64-4286-BB8B-B0260EE20B80}` |
| 2025 specific path entry | `{903A30EC-F1F4-49FF-9CBC-99B89539598B}`: InGame `{7C400264-0402-4E47-930D-960FBDD8605B}` × None `{4BA09D62-D59B-4880-A78C-8BECE7D7899F}` → Stealth `{20FA9A69-7ECC-4B05-BD6B-2C9527CD88C2}` |
| 2025 sibling path entry | `{7AE5D86A-30A6-4AC9-A909-C57953EE03BE}`: InGame × c_Fight `{20A3B196-D22F-42F7-8592-A37A3E5B467A}` → Fight `{1D0ECA1F-2749-4DBB-B92C-0DBDFDA7A825}` |
| 2025 fallback-like group path | `{BB6519A2-1173-4569-B1F6-57305FEBB759}`: Music_Global group × Music_inGame group → the second container's Stealth `{20FA9A69-7ECC-4B05-BD6B-2C9527CD88C2}` |

Do not confuse the two different Stealth objects merely because their names
match. Do not reuse 2025 entry GUIDs as 2022 entry identities: the inspected
2022 XML stores these paths as `Entry` elements without those GUID attributes.
Group references in a path must not be guessed to mean a wildcard without
versioned/native evidence; preserve their exact identity while probing.

Fixture locations: [2022 Stealth Playlist](../../tests/_org/2022.1/Interactive%20Music%20Hierarchy/Music.wwu#L1586),
[2022 Transition](../../tests/_org/2022.1/Interactive%20Music%20Hierarchy/Music.wwu#L1574),
[2022 two-dimensional container](../../tests/_org/2022.1/Interactive%20Music%20Hierarchy/Music.wwu#L7711),
[2025 Playlist](../../tests/_org/2025.1/Containers/Music/Music.wwu#L281),
[2025 Transition](../../tests/_org/2025.1/Containers/Music/Music.wwu#L327),
[2025 two-dimensional container](../../tests/_org/2025.1/Containers/Music/Music.wwu#L7211).

## #119: Playlist entries, order, and looping

### What is present

Both installed definitions have MusicPlaylistItem scalar properties including
Playlist Item Type, Play Mode, Weight, and No. of Loops. Play Mode explicitly
discloses Sequence Continuous/Step and Random Continuous/Step. LoopCount has
an enabled-state dependency on IsLoopingInfinite; its documented lower bound
differs between these installed versions (-1 in 2022, 0 in 2025). The probe
must use live disclosed labels/restrictions, never carry enum integers or
infinite-loop semantics from one lane to the other.

2025 adds a non-null MusicPlaylistItem Segment reference, and its
MusicPlaylistContainer exposes a non-null, custom-object PlaylistRoot
reference. The inspected 2022 definitions lack those explicit metadata
references. The WWUs reflect the distinction: 2022 serializes `Playlist` and
`SegmentRef`; 2025 serializes PlaylistRoot/Custom and Segment/ObjectRef. Both
contain the same ordered three-item Stealth tree.

Installed metadata anchors: 2022 WObjects.xml MusicPlaylistItem at line 1047,
LoopCount at 1132, MusicPlaylistContainer at 6195; 2025 MusicPlaylistItem at
1020, LoopCount at 1105, MusicPlaylistContainer at 6420. These are offline
disclosure observations, not proof of the live WAAPI exposure on every host.

### Current Gateway limits

- `draft-discover-types --role object` accepts non-source/effect categories,
  including WObject/Inner; discovery does not certify valid placement.
  [dispatch_business_type_discovery](../../skills/waapi-skill/scripts/gateway.py#L18122)
- MusicPlaylistItem is recognized as an anonymous, non-renamable owned entry.
  It is not in `_resolve_object_type`'s native creation prohibition list.
  Nevertheless, it is absent from writable hierarchy parents, so its nested
  children fail the ordinary child capability guard.
  [identity/parent capabilities](../../skills/waapi-skill/wwise_waapi/object_capabilities.py#L70),
  [creation guard](../../skills/waapi-skill/wwise_waapi/operation_registry.py#L6649)
- `NewDescendantTarget` validation still requires a nonempty name. An
  anonymous Playlist item is not equivalent to inventing a display name.
  [target normalization](../../skills/waapi-skill/wwise_waapi/business_declaration_state.py#L632)
- Ordinary property/reference fields can target existing bound objects; the
  graph declaration does not expose an inline new custom object behind a
  reference such as PlaylistRoot. Setting a reference to a bound object is
  not that construction operation.
  [field compiler](../../skills/waapi-skill/wwise_waapi/object_graph_business.py#L477)
- Generic object-set list verification compares GUID sets. It does not prove
  child ordering, repeated Segment occurrences, or a playback sequence.
  [list verification](../../skills/waapi-skill/wwise_waapi/operation_registry.py#L16825)

### Smallest extension if existing-field probes succeed

Keep simple loop/mode/Segment edits on existing property/reference handles.
For full A→B→A construction, add a reviewed placement/outcome to the existing
object business seam only after native support is proven in the selected
lane: exact playlist owner, ordered item/group declarations, existing Segment
handles, disclosed mode, finite repetitions/infinite intent. Gateway owns
PlaylistRoot/custom-object construction, anonymous identity, recursive
placement, native tokens, and dependency order. It must distinguish repeated
occurrences of one Segment from duplicate item GUIDs.

Do not merely add MusicPlaylistItem to all ordinary writable parents or expose
raw custom-reference JSON. Any general placement primitive must be scoped to
catalog-proven owner/field/item combinations and preserve current prohibition
of Clips, Sequences, and Stingers creation.

Oracle: exact ordered tree of `(item GUID, item kind, Segment GUID, ordered
children, play mode, loop state/count)`, plus unchanged non-target items and
container references. An unordered member set is insufficient. A query's
returned row order is not automatically authoritative playback order; first
prove an order accessor or use an independent saved-sandbox WWU inspection
after an authorized save. If order cannot be exposed/attested, keep complete
order acceptance blocked. Audible execution order requires a separate bounded
playback oracle, not a larger scalar test.

## #120: existing Transition fields and fades

Both installed MusicTransition definitions expose context type/reference,
Exit Source At, cue-match name, source post-exit, destination synchronization,
destination pre-entry, and fade enable flags. Their enum display labels and
dependencies are concrete metadata, suitable for live field discovery. In
2022 SourceContextObject/DestinationContextObject restrictions use the
InteractiveMusic category; 2025 lists accepted concrete types. Check whether
the current live metadata restriction parser accepts the exact returned form
before calling either lane supported.

2025's Common_TransitionNode exposes TransitionRoot as a custom reference;
2022 stores its transition graph in TransitionList. The existing exact rule
GUID above avoids requiring new rule creation and is the preferred first
probe. A live bracketed/derived identity may still require identity-semantics
review: MusicTransition and MusicFade are not currently listed alongside
MusicPlaylistItem in the special non-intrinsic identity table. Do not repair
such a failure by fabricating a new name or path.

Fade Time, Fade Offset and Fade Curve belong to **MusicFade**, not ordinary
MusicTransition scalar fields. The WWU has TransitionInfo/SourceFadeOut (and
other roles) containing these objects. A successful Enable Source Fade-out
write proves only the flag. The installed metadata does not by itself prove a
public parent→specific MusicFade role traversal; use existing fade GUIDs only
after independently establishing their owner/role. Action-only milliseconds
business fields must not be reused as a music fade unit conversion shortcut.

Metadata anchors: 2025 Common_TransitionNode at 2465, MusicTransition immediately
after that shared-base section, and MusicFade at 2712; 2022 MusicFade at 2731.
See also the current [field discovery](../../skills/waapi-skill/wwise_waapi/business_declarations.py#L1043),
[metadata mutation compiler](../../skills/waapi-skill/wwise_waapi/object_metadata_business.py#L129),
and [versioned metadata contract](../../skills/waapi-skill/wwise_waapi/object_metadata_business_contracts.py).

First implementation choice: if exact identity, discovery, scalar mutation and
readback work, add focused coverage without introducing a new runtime route.
If the eventual task includes several dependent context/cue/fade changes,
compose the existing field operations or extend one operation-local business
plan with explicit meanings. Do not mistake field-by-field success for an
atomic complete-rule compiler. A dependency field currently disabled by the
old mode may require an ordered, separately previewed transition rather than
being silently bypassed during discovery.

Oracle: exact rule GUID, context type and source/destination GUIDs, intended
scalar outcomes, corresponding MusicFade role/value tuples, unchanged sibling
rules/order, and preserved TransitionRoot ownership. A narrowly scoped scalar
probe can pass without proving new rules, cue scheduling or audible fades;
report that scope precisely.

## #121: Music Switch multi-dimensional paths

The two-dimensional `02_In-Game Music` fixture exists in both versions and
already supplies concrete argument order and multiple specific/group-valued
paths. No generated synthetic native path shape is needed to begin discovery.

2022 installed MultiSwitchEntry exposes only Probability and Weight in its
local WObjects definition. Its MusicSwitchContainer local definition does not
expose the later Arguments/Entries object lists. The 2022 WWU stores an
ArgumentList and EntryList with PathElementRef and AudioNodeRef. The type
catalog still lists MultiSwitchEntry; that is not proof that the later
AudioNode or EntryPath fields can be accessed through 2022 live metadata.

2025 exposes:

- MusicSwitchContainer Arguments: MusicArgumentsSlot objects with Argument
  references to StateGroup/SwitchGroup.
- MusicSwitchContainer Entries: MultiSwitchEntry objects.
- MultiSwitchEntry AudioNode: a reference accepting music containers/segments
  as well as several ordinary audio types.
- MultiSwitchEntry EntryPath: EntryPathSlot objects with EntryPathObject
  references to groups or their State/Switch values.

Installed anchors: 2022 MultiSwitchEntry at 1431 and MusicSwitchContainer at
6207; 2025 MultiSwitchEntry at 1434 and MusicSwitchContainer at 6435. The
[2025 packaged type catalog](../../skills/waapi-skill/resources/metadata/2025.1/object-types.json#L166)
classifies EntryPathSlot and MusicArgumentsSlot as `Inner`; the
[2022 catalog](../../skills/waapi-skill/resources/metadata/2022.1/object-types.json#L216)
does not contain those two slot names.

The narrow existing-entry target change may already fit `object.setReference`.
Full path creation does not fit the current recursive list compiler:
`_materialize_set.compile_node` rejects nested object lists with
`OBJECT_SET_NESTED_LIST_UNAVAILABLE`; ordinary parent validation also excludes
MultiSwitchEntry as a writable parent. Anonymous EntryPathSlot and
MusicArgumentsSlot are not in the special identity table, so binding existing
slots may fail independently of the list compiler.
[set materializer](../../skills/waapi-skill/wwise_waapi/object_graph_business.py#L1228),
[identity capabilities](../../skills/waapi-skill/wwise_waapi/object_capabilities.py#L70).

Minimal complete-outcome extension, if the native lane is proven: exact music
container handle; ordered existing argument-group handles; one or more
ordered path tuples with explicit group/value handles and one existing music
target handle per tuple; bounded add/update/remove intent. Gateway owns the
2025 wrapper objects and the exact supported earlier-version representation.
Never expose wrapper names/class IDs or reuse ordinary
`switchContainer.addAssignment` as if it represented a multi-dimensional
Music Switch path. Prefer this scoped business outcome over broad recursive
raw-list composition.

Oracle: ordered group IDs, exact path tuple→AudioNode mapping, slot/entry
identities where stable, no duplicate tuples, path width matching arguments,
each value's group membership, unchanged unselected tuples and the default or
group-valued routes. A set of all State/Switch GUIDs loses tuple association
and is an invalid oracle. Do not infer runtime wildcard/priority semantics
from XML group references alone.

## Root-coordinated public sandbox probe plan

This is a proposed runbook, not an executed script. Root coordinates every
real process. Use the existing lifecycle to copy the matching committed
SampleProject into a fresh owned sandbox, prove source full hash/mtime, attest
actual host/build/project, and save all Gateway outputs and transaction
artifacts. Never open `tests/_org` directly. Run versions sequentially.

All calls use `python skills/waapi-skill/scripts/run.py gateway.py ...` with
the owned test state/config/endpoint envelope supplied by the established
runner. The suffixes below are literal read commands; no temporary Python or
direct WaapiClient is authorized. Copy every returned continuation by its
declared source field; do not manufacture draft IDs/revisions/field handles.

### Probe A: existing Playlist loop field and exposed graph

1. `query-object --exact-id '{492A2BCA-08ED-4ED9-BDA3-B4D876D2D830}' --include-field 'Playlist Root'`.
   Record a missing/ambiguous reference honestly, particularly on 2022.
2. `query-object --exact-id '{DE090E27-2F5C-436F-A239-D02F8D5016B2}' --include-field 'No. of Loops' --include-field 'Playlist Item Type' --include-field 'Segment'`.
   If one unresolved meaning prevents the combined query, use separately
   scoped, distinct follow-ups; do not repeatedly retry the same failed input.
3. Read the root's children with the business relationship and a 16-row bound.
   Verify identities against the three fixture items; record ordering as an
   observation, not a contractual playback-order proof.
4. Start `object.setProperty`, bind only the exact first item GUID, discover
   No. of Loops, inspect live dependency/restrictions, and declare a finite
   value of 2 only if enabled and admissible. Preview must name one scalar
   update, not a new Playlist/item. Root may authorize/execute once under the
   normal policy lifecycle and then independently repeat the exact-ID read.
5. Require unchanged item/Segment IDs, sibling values and tree membership.
   The result is **existing loop-property evidence**, not Playlist creation
   or order evidence. If disabled because of infinite-loop state, record the
   boundary; do not inject an undisclosed flag or replace the item.

### Probe B: one existing Transition boolean

1. `query-object --exact-id '{B24173D4-7534-4C19-ACE0-F1F1B0EBD535}' --include-field 'Play Source Post-exit' --include-field 'Play Destination Pre-entry' --include-field 'Exit Source At'`.
2. Start `object.setProperty`, bind that GUID, discover Play Source Post-exit,
   and declare false through the selected field handle. Stop if live identity
   or field discovery rejects it; report the precise public stage/error.
3. Preview/authorize/execute/verify once. Independently check the target false,
   destination pre-entry and Exit Source At unchanged, and no new rule/root.
4. A second, separate probe may select the live-disclosed Exit Source At label
   “Next Bar”; never provide its native integer. Do not combine this with cue
   matching or MusicFade until their prerequisites and oracle are available.

This probe can establish a supported existing-rule maintenance slice before
any new API/DSL work. It cannot establish audible scheduling or full fades.

### Probe C: 2025 existing multi-path target, with full preservation

1. Read `02_In-Game Music` by exact ID. Disclose `query-schema --advanced`
   only for the collection traversal that the closed relationship layer
   cannot express. The fixed read expressions to test are:
   `from object "{A9D070F3-3BD9-49EB-9D8B-5D3312173FB4}" select @Arguments`
   and the same source with `select @Entries`, each `--max-results 16`.
   They are grounded accessor candidates from 2025 metadata, not claims of
   executed WAQL. Stop on native rejection; no syntax guessing loop.
2. Read each returned argument slot by exact ID with include-field Argument.
   For each entry, read Audio Node and separately traverse its EntryPath;
   exact-ID each returned path slot with include-field EntryPath Object.
   Keep ordered tuples. Canonical relationship GUIDs used as read-only hops
   do not require a mutation-selection user turn.
3. Before a mutation, exact-ID re-read the selected entry
   `{903A30EC-F1F4-49FF-9CBC-99B89539598B}` and chosen target. If the complete
   prestate mapping cannot be reconstructed, do not proceed with a
   “preserve all other paths” claim.
4. In the sandbox only, use `object.setReference` with a live Audio Node
   field handle to repoint that entry to the existing Fight target
   `{1D0ECA1F-2749-4DBB-B92C-0DBDFDA7A825}`. Preview/authorize/execute once.
   Verify only that exact path tuple's target changed; all other tuples,
   arguments, slots and entry identities are unchanged.
5. On 2022, first perform analogous discovery against its actual live object
   model. Do not reuse 2025 slot/entry GUIDs or assert a native limitation
   merely because metadata differs. Record whether the public lane can
   reconstruct the complete mapping before considering a mutation.

Only if these current-path probes fail at a reproducible interface boundary
should runtime work begin. Preserve each failed/blocked sandbox and its exact
candidate evidence. Add focused fake/public-Gateway regression for the
demonstrated gap before a repair, then a new sandbox root; do not weaken
anonymous identity, creation, ordering, or metadata guards to make a probe pass.

## Expected engineering sequence

1. Run A/B read stages on 2025, then 2022, and C's 2025 read stages under the
   single root coordinator. They determine disclosure versus identity versus
   graph-construction failures without changing projects.
2. Prove the narrow existing-field mutations only where all public preconditions
   and independent postconditions are available. They can add useful supported
   slices without pretending #119/#120/#121 are fully complete.
3. Design only the demonstrated missing seam: reference-owned/nested anonymous
   placement and ordered Playlist oracle; explicit fade-role traversal if
   absent; versioned Music Switch tuple construction/readback. Publish each
   through its Registry/Gateway contract, immutable preview, drift checks,
   execute-once lifecycle and appropriate verifier.
4. Keep native result-schema acceptance, persisted graph-state proof, and
   playback semantics as separate evidence levels. Extend Fresh Agent cases
   only after the actual public workflow is executable and the oracle is sealed.

No live outcome is claimed by this note. Metadata absence, unsupported public
placement, native rejection, missing business oracle, and failure of audible
behavior remain distinct possible results of the planned probes.
