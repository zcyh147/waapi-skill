# Conversion codec placement and configuration, #179

The existing 2024.1/2025.1 `ak.wwise.core.audio.setConversionPlugin` Business
Draft now uses the [user-approved lightweight wrapper boundary](../plans/full-waapi-coverage/SPEC.md#user-approved-lightweight-wrapper-acceptance--2026-10-27):
closed mapping and code controls, with native-result-only verification. Native
setter effects and platform association remain unverified. Older exact-GUID
read/field effects below are separate evidence. #179 and build/conversion #183
remain open; no further native QA or platform-mapping research is required by
this increment.

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
`object.get` documents its platform option. The retained native observations
below show that this option does not establish a one-codec-per-platform
identity mapping. The setter no longer enumerates codecs or snapshots their
fields as a precondition, and it never chooses a row from those results.

Before one setter execution the Gateway rechecks the exact Conversion
identity, complete bounded platform catalog and selected installed class.
The immutable Preview discloses that prior codec properties may reset.
Verification validates the empty reflected native result and ends
`result_schema_checked`, `verified=false`, `business_state_verified=false`.
Actual replacement, platform-to-codec GUID association and other platform codec
or field preservation remain unverified. Historical previews that promised the
stronger placement verifier require recreation before execution.

No codec GUID or automatic configuration continuation is returned. A separately
chosen exact live codec GUID may enter the existing `object.setProperty` Draft.
Live exact-object Field Handles select scalar properties, value domains and
conditions; configuration has its own Preview, authorization, single execution
and readback. An unresolved request for a named platform's codec property
remains a boundary, rather than permission to guess an identity.
ConversionPlugin Work Unit elements have `Name=""`; the retained Console
2025.1.7.9143 packet returns the opaque path `<Unnamed Conversion plugin>`.
The existing ConversionPlugin identity semantics preserve that bounded,
non-control display text without granting selector or platform authority.
Ordinary field binding retains its GUID/name/type/path and Field Handle
metadata revalidation contract.

## Five pinned source lanes

Sources are the matching installed Authoring `Data/WObjects/WObjects.xml`,
`x64/Release/bin/plugins/DefaultConversions.xml`, installed SDK CHM pages and
the committed `tests/_org/<version>/Conversion Settings/Default Work Unit.wwu`.
None of these project sources was opened in Wwise or modified.

| Build | Codec declaration and placement | Current public selection/configuration |
| --- | --- | --- |
| 2021.1.14.8108 | ConversionPluginInfoList contains anonymous per-platform codec GUIDs; installed codec classes discovered as Conversion | Exact-GUID read/metadata and one live-bound QualityFactor scalar change proven; arbitrary codec replacement/platform lookup unresolved |
| 2022.1.19.8584 | Same persisted topology, independently inspected | Exact-GUID read/metadata proven; shared FieldHandle configuration program-tested; arbitrary replacement/platform lookup unresolved |
| 2023.1.19.8928 | Same persisted topology, independently inspected | Exact-GUID read/metadata proven; shared FieldHandle configuration program-tested; arbitrary replacement/platform lookup unresolved |
| 2024.1.13.9056 | Same topology plus reflected setter and documented ConversionPlugin getter example | Closed Type Handle/platform setter with result-only verification; exact-GUID Field Handles remain separate |
| 2025.1.7.9143 | Same topology plus matching reflected setter/getter example | Same result-only wrapper; native placement/platform association unverified |

`object.create` in 2021 has no classId field; a native `Conversion` ShareSet
creation is distinct from choosing its embedded codec. Neither XML PluginID
arithmetic nor an invented `@ConversionPlugin`/`@ConversionPluginInfoList`
member is a documented setter. The WObjects Conversion declaration exposes
scalar audio settings, not a codec reference/list for those older APIs.
`object.copy` is the source-supported whole-object alternative: it can retain a
known donor Conversion's codec setup, but does not establish arbitrary codec
replacement or platform isolation. Absence of the newer setter, missing getter
examples or these source findings do not prove native impossibility. Earlier
arbitrary attachment remains assigned to #179 with #183 coordination.
The matching 2024/2025 `getProjectInfo` definitions expose the required
`defaultConversion` reference (`id`, `name`), explicitly described as the
Project's default Conversion Settings object. This supplies the ordinary
Conversion GUID for the existing setter; it does not establish Project GUID
acceptance. The collector records that reference and its exact-ID/type/class
readback, reusing the named PCM observation when it is the actual project
default. An unresolved default diagnostic remains separate from the named
Conversion workflow outcome.

## Complete installed DefaultConversions field mapping

All four installed definitions declare `PlatformSupport/Platform Name="Any"`
in each of the five builds. That is source support, not a claim that every
possible third-party codec or platform combination executes successfully.
Live getTypes availability and field metadata remain authoritative.

| Class | 2021/2022/2023 scalar names | 2024/2025 scalar names | Public route |
| --- | --- | --- | --- |
| ADPCM | FixLoopMethod | none | Existing exact codec Field Handles on a chosen reachable GUID; no class replacement |
| WEM Opus | Quality | Quality | Same shared field route |
| PCM | none | MaxBitDepth | Same shared field route |
| Vorbis | BitrateManagmentMode, QualityFactor, AverageBitrate, EnableMinimumBitrate, MinimumBitrate, EnableMaximumBitrate, MaximumBitrate, BitReservoirTime, ReservoirBiasFactor, AverageTrackSlewTime, EnableAdvancedSettings, SeekTableGranularity, RenderLineAlgo | Same except RenderLineAlgo is removed | Same shared field route; no per-codec field allowlist |

The Conversion Settings object's own scalar names are mapped by its existing
exact-object Field Handle route. Live metadata supplies their types, legal
values and conditions. No enum values or optional permutations were removed
to fit the representative functional test selection. The setter invocation and a separately chosen exact-GUID Vorbis QualityFactor
change are separate program cases; this is not
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

Program tests use the actual public Gateway and a fake external native client.
They check closed mapping, exact authority drift refusal, one setter without
codec enumeration, result-only acknowledgement, historical-preview refusal and
the separate exact-object field workflow. They do not prove native codec
attachment, platform preservation, Windows, build or Fresh behavior. #195 owns
the final stable combined Program/Non-live gates.

The retained stronger native node is
`test_gateway_workflow_transaction_matrix.py::test_conversion_plugin_placement_and_field_configuration`.
Its existing collector still demands independently verified placement and a
second scalar transaction. It is unchanged and receives no PASS credit from
this result-only wrapper. Its fake-producer regression now checks that a weak
setter result stops before the scalar change and remains a finalized FAIL with
quarantined evidence. The read-only metadata-probe regression remains separate.
No new native attempt is part of this increment.

## Retained native observations and current boundary

Main's frozen144acba7 Console2025.1.7.9143 attempt ended in the original
**FAIL**,14.60s, after three public read calls and before any transaction.
With explicit Mac platform GUID, the owner-filtered query returned both PCM
codec GUIDs. This proves that the platform option did not filter those object
identities; no first-row or saved-file association may be inferred. The source
full-tree hash/metadata/project mtime were preserved, process cleanup completed,
and the failed sandbox was quarantined. The original category and assessment
remain under `.waapi-skill-state/full-coverage/conversion-179-2025-native-r1/`.
DefaultConversion independently resolved to the named PCM Conversion GUID.

The separate `conversion-179-2025-metadata-r1` diagnostic at `73f944c7` was
**PASS, 5.58s**, zero writes/transactions; business category remains **blocked**.
Both complete PCM inventories disclosed only scalar MaxBitDepth, no platform or
reference field. The historical wrapper refused ambiguous owner results; this does not
prove that the documented setter cannot set a codec. The current user-approved wrapper accepts result-only verification and removes
that enumeration prerequisite; no modern setter effect has been accepted live.

Older exact-GUID reads/QualityFactor metadata are now native-proven. Original
read-r1 SKIPs remain: 2021 **9.26s**, 2022 **4.31s**; raw class 2818064/empty
pluginName describe a generic wrapper, not concrete Vorbis. Pinned-wrapper
metadata-r2 passed **5.94s/4.07s**; 2023 read-r1 passed **4.39s** with 262145/Vorbis.
One 2021 FieldHandle scalar case at `a47152b7` passed **6.35s**, VERIFIED 3→4 with
exact GUID/name/type/opaque path/owner/raw class/pluginName retained. After the
shared opaque-identity correction (`73f944c7`), the existing object.setProperty
route required no further production change. Source GUIDs are test oracles; ordinary changes require exact
chosen live GUIDs and live FieldHandles. No replacement or platform lookup is
credited. Sources/processes were preserved/cleaned; nonpasses stay frozen. Exact
roots/receipts: [test inventory](../../tests/TEST_INVENTORY.md).

Matching 2024.1.0 **WG-71956** introduces the named setter (and audio.convert).
Matching 2024.1.13.9056 SDK CHM/member whatsnew_2024_1_0.html SHA-256:
`aa6b467caae07c2363806adc1dadeed8df7a29c4bdf2d23fd629126208054364` / `bd674dcc2897bb519f01fe4029bd911f4e1ef765ae4073e88b93d6b53892dd18`.
This dates the setter, not older read/property availability; #179 remains open.
The 2021 Sink/Metadata direct-constructor decision is separately pending.
