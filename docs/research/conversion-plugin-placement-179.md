# Conversion codec placement and configuration, #179

This increment strengthens the existing 2024.1/2025.1
`ak.wwise.core.audio.setConversionPlugin` Business Draft. It is program-tested,
not native execution evidence. Build/conversion execution remains #183.

The public plan binds an exact Conversion Settings object, one live project
platform and one installed Conversion Type Handle. The Gateway derives the
native `plugin` name from that handle. No codec names, numeric class IDs,
native query, native args or options are accepted as substitute authority.
The setter has exactly three native fields (`conversion`, `platform`, `plugin`)
and no native options. All three are mapped. Any discovered installed Conversion
class and any exact existing project platform remain selectable; there is no
PCM/Vorbis allowlist. The platform name retains its reflected native spelling,
while its GUID and complete catalog are sealed and revalidated.

The matching 2024/2025 SDK example
`ak_wwise_core_object_get_example_getting_all_conversion_plug_ins.html` documents
`from type conversionplugin` and the `pluginname`, `id`, `owner.name` and
`classid` projections. `waql_reference.html` documents owner expressions;
`object.get` documents its platform option. Gateway-owned observation filters
by the exact owner's GUID, fixes a two-row ambiguity sentinel, and reads each
project platform by its GUID. Before one setter execution it rechecks the
Conversion identity, platform catalog, installed class and complete bounded
codec field snapshots. Final verification checks the selected codec's class,
name and owner independently of the setter's empty result, preserving the
other platforms' codec GUIDs, classes and returned fields.

After successful attachment, the returned codec GUID can enter the existing
`object.setProperty` Draft. Live exact-object Field Handles select scalar
properties, value domains and conditions; configuration has its own Preview,
authorization, single execution and readback. ConversionPlugin Work Unit
elements have `Name=""`; the shared identity rules now admit that exact
anonymous type, preserving the existing path validation. Actual native path
representation still needs the selected native observation; no reconstructed
path or synthetic name is provided to callers.

## Five pinned source lanes

Sources are the matching installed Authoring `Data/WObjects/WObjects.xml`,
`x64/Release/bin/plugins/DefaultConversions.xml`, installed SDK CHM pages and
the committed `tests/_org/<version>/Conversion Settings/Default Work Unit.wwu`.
None of these project sources was opened in Wwise or modified.

| Build | Codec declaration and placement | Current public selection/configuration |
| --- | --- | --- |
| 2021.1.14.8108 | ConversionPluginInfoList contains anonymous per-platform codec GUIDs; installed codec classes discovered as Conversion | Whole Conversion Settings copy retains donor settings through the existing object.copy lane; arbitrary codec replacement and owned-codec discovery/configuration remain unresolved |
| 2022.1.19.8584 | Same persisted topology, independently inspected | Same unresolved replacement/configuration; object.set docs restrict classId selection to Effect/Source |
| 2023.1.19.8928 | Same persisted topology, independently inspected | Same unresolved replacement/configuration; object.set docs restrict classId selection to Effect/Source |
| 2024.1.13.9056 | Same topology plus reflected setter and documented ConversionPlugin getter example | Installed Type Handle selection, exact platform binding and independent attachment verifier; exact codec Field Handle configuration |
| 2025.1.7.9143 | Same topology plus matching reflected setter/getter example | Same shared mechanism |

`object.create` in 2021 has no classId field; a native `Conversion` ShareSet
creation is distinct from choosing its embedded codec. Neither XML PluginID
arithmetic nor an invented `@ConversionPlugin`/`@ConversionPluginInfoList`
member is a documented setter. The WObjects Conversion declaration exposes
scalar audio settings, not a codec reference/list for those older APIs.
`object.copy` is the source-supported whole-object alternative: it can retain a
known donor Conversion's codec setup, but does not establish arbitrary codec
replacement or platform isolation. Absence of the newer setter, missing getter
examples or these source findings do not prove native impossibility. Earlier
attachment/configuration and implicit Project/default target applicability
remain assigned to #179 with #183 coordination.

## Complete installed DefaultConversions field mapping

All four installed definitions declare `PlatformSupport/Platform Name="Any"`
in each of the five builds. That is source support, not a claim that every
possible third-party codec or platform combination executes successfully.
Live getTypes availability and field metadata remain authoritative.

| Class | 2021/2022/2023 scalar names | 2024/2025 scalar names | Public route |
| --- | --- | --- | --- |
| ADPCM | FixLoopMethod | none | Existing exact codec Field Handles where codec identity is reachable; older reachability unresolved |
| WEM Opus | Quality | Quality | Same shared field route |
| PCM | none | MaxBitDepth | Same shared field route |
| Vorbis | BitrateManagmentMode, QualityFactor, AverageBitrate, EnableMinimumBitrate, MinimumBitrate, EnableMaximumBitrate, MaximumBitrate, BitReservoirTime, ReservoirBiasFactor, AverageTrackSlewTime, EnableAdvancedSettings, SeekTableGranularity, RenderLineAlgo | Same except RenderLineAlgo is removed | Same shared field route; no per-codec field allowlist |

The Conversion Settings object's own scalar names are mapped by its existing
exact-object Field Handle route. Live metadata supplies their types, legal
values and conditions. No enum values or optional permutations were removed
to fit the representative functional test selection. Representative behavior
is class selection plus a separate Vorbis QualityFactor change; this is not
per-codec/value QA or audio-quality proof.

## Immutable source digests

SHA-256 of installed DefaultConversions.xml:

| Builds | Digest |
| --- | --- |
| 2021.1.14.8108 / 2022.1.19.8584 / 2023.1.19.8928 | 0e736ef1c334091ea0c5992d05ff1b2e37c3f7a6117153fad709ca2af5ffc095 |
| 2024.1.13.9056 / 2025.1.7.9143 | 21e07225bb0a4f861516b96b1130fcf27df709433a748faa915421cc29793f7c |

SHA-256 of matching decompressed SDK HTML bytes:

| Lane / member | Digest |
| --- | --- |
| 2021 wwiseobject_conversion.html | ef00ca1afb6ab4173c647695f211b7d4ab210716c8e6b22b45ce23ddd01cab73 |
| 2022 wwiseobject_conversion.html | 08c7e2ef4c135e281afb4c780fc9cedf83a1dcb3850a98e5b714df1ec45043c9 |
| 2023 wwiseobject_conversion.html | 3380b6dcfbc8efde258c78ffbcd96d1a4a2ab5773e5e97144b01bcde3c9f86d5 |
| 2024 wwiseobject_conversion.html | 7c9804466c67a85f76aaa3b31bed368559ffdcf635dc738c1374b1c3bd1c8a5d |
| 2025 wwiseobject_conversion.html | 1cb0e2828430b08e8867ec5fae98c5f0fad5f260be8d12cc845304bd47453334 |
| 2021 ak_wwise_core_object_copy.html | bd89d71208e1631b0ccfb5c0b8fe54d13f8350dd19133d45d75cd5a4e1d3fafb |
| 2022 ak_wwise_core_object_set.html | 1e2184bdb8208072aa793253de7b987a75b9ad564e69f4d1ed513fcd5e05a326 |
| 2023 ak_wwise_core_object_set.html | 18feb6864dc219f6468b32c1670db14b6a23138c2d27bb5028a82310026b5a3d |
| 2024 ak_wwise_core_object_get_example_getting_all_conversion_plug_ins.html | 2df76a51af2b2b8107444c1523876c42448cb6afc6cf418adfac2af791c67136 |
| 2025 same getter example | 33050b4d1ad02278cf33f033af30d172c1ed6ebd0609af934bc48e543806a835 |
| 2024 ak_wwise_core_audio_setconversionplugin.html | beeac6ee222e18d578c6fb73e8e49d07df4ec4dfe40b2605a9d2ca3871f55166 |
| 2025 same setter page | 44e885a4e25c80ed7cd51d15df4423d11c2950425cca0a78875028f59760f5dd |

Program tests use the actual public Gateway and fake external native client.
They prove closed mapping, installed class/platform drift refusal, a truthful
failed business result after an empty native acknowledgement, other-platform
preservation, and the separate exact-object field workflow. They do not prove
native codec creatability, native accessor admission, Windows, build or Fresh
behavior. #195 retains the stable combined Program/Non-live gates.
