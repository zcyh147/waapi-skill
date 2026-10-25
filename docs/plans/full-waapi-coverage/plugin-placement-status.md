# Plugin placement checkpoint for #179

This is an implementation checkpoint under #174, not completion or native
execution evidence. The public seam is the existing Gateway Business Draft,
Type/Field Handles, immutable Preview, authorization, one execution and
independent verification. No native process was launched for this increment.

## Exact version and kind accounting

| Pinned build | SourcePlugin | EffectPlugin | SinkPlugin | ConversionPlugin | MetadataPlugin |
| --- | --- | --- | --- | --- | --- |
| 2021.1.14.8108 | Discovery; constructor unresolved | Discovery; constructor unresolved | Discovery; constructor unresolved | Discovery; attachment alternative unresolved | Discovery; constructor unresolved |
| 2022.1.19.8584 | Source child | Owner fixed slots / independent ShareSet | Independent AudioDevice ShareSet | Discovery; attachment alternative unresolved | Independent Metadata ShareSet |
| 2023.1.19.8928 | Source child | Owner EffectSlot append / independent ShareSet | Independent AudioDevice ShareSet | Discovery; attachment alternative unresolved | Independent Metadata ShareSet |
| 2024.1.13.9056 | Source child | Owner EffectSlot append / independent ShareSet | Independent AudioDevice ShareSet | Installed Type Handle / platform setter; exact codec Field Handles | Independent Metadata ShareSet |
| 2025.1.7.9143 | Source child | Owner EffectSlot append / independent ShareSet | Independent AudioDevice ShareSet | Installed Type Handle / platform setter; exact codec Field Handles | Independent Metadata ShareSet |

Creation rows describe implemented Gateway construction and model controls.
They do not establish successful native creation or a host/build equivalence.
The Source/Effect construction predates this increment. The conversion route
selects a platform codec on a Conversion Settings object; it is not a generic
Conversion child constructor. Its existing route does not discharge all plugin
field, attachment or outcome obligations in #179/#183.

The Sink native catalog category is AudioDevice. It cannot satisfy an Effect
Type Handle role. Independent Effects require an Effects Work Unit, Sinks an
Audio Devices Work Unit, and Metadata a Metadata Work Unit. Existing names fail;
no replacement or list reset is offered. Independent creation seals all direct
children, rechecks the whole pre-state before dispatch, then independently
checks the exact new identity/class/parent and every preserved child.

Plugin class references now use class-scoped Reference Field Handles and exact
bound target handles in the same creation call. Target identity/type and known
reference classifiers use the existing reference planner. Explicit references
also enter the class/default condition compiler. Omitted native name/type is
preserved: a missing name requires separate exact same-scope names evidence,
and a missing reference type requires an explicit reference restriction. A
scalar type is never inferred. Requested reference readback is checked by GUID,
separately from native creation success; metadata omission drift blocks writes.

## Source facts, separated from creatability

Matching installed sources were read under
`/Library/Application Support/Audiokinetic/Wwise <build>/Authoring/`.
The existing reflected `resources/metadata/<version>/object-types.json` files
provide independently recorded native class IDs; runtime still selects live
getTypes rows. IDs are never calculated from XML CompanyID/PluginID.

All five installed `x64/Release/bin/plugins/AkSystemOutput.xml` files declare
MetadataPlugin **Wwise System Output Settings**, CompanyID 0 / PluginID 900,
with Mix Behavior choices Use Default, Mix to Main and Mix to Passthrough. The
2024/2025 source additionally declares exclusive RTPC support. Its reflected
class is 58982409; discovery still requires that exact live class to exist.

| Source build | AkSystemOutput.xml SHA-256 |
| --- | --- |
| 2021.1.14.8108 | d1024dbf0198853d43f81d591fd5c9005d52094bbd311a11446656bae821fcc2 |
| 2022.1.19.8584 | d1024dbf0198853d43f81d591fd5c9005d52094bbd311a11446656bae821fcc2 |
| 2023.1.19.8928 | d1024dbf0198853d43f81d591fd5c9005d52094bbd311a11446656bae821fcc2 |
| 2024.1.13.9056 | 1e7d4e08cf0b2954bdb2cb024ed2144ffe8892ff7acef3fe4c61b61805a6293e |
| 2025.1.7.9143 | 1e7d4e08cf0b2954bdb2cb024ed2144ffe8892ff7acef3fe4c61b61805a6293e |

Matching `Data/WObjects/WObjects.xml` supplies AudioDevice, Effect, Metadata,
Conversion and MetadataSlot source topology. Committed disposable-project source
Work Units independently distinguish device ShareSets from platform-specific
ConversionPluginInfoList entries. These are source/construction facts. They do
not prove a native API admits any proposed placement or that its business effect
succeeds. No committed project was opened or modified.

## Remaining obligations

- **2021.1 alternative construction (#179):** object.create has no classId and
  object.set is absent from that lane. Determine legal native alternatives for
  each kind using matching native evidence. Do not guess numeric object types,
  infer absence from one failed classic spelling, or bypass the Gateway.
- **Owner metadata (#179):** native source exposes MetadataSlot and its Metadata
  reference; creation/append, OverrideMetadata applicability, preservation and
  native effects remain implementation and evidence work. An independent
  Metadata ShareSet is not credit for this branch.
- **Sink attachment (#179):** selection on a Bus is distinct from independent
  AudioDevice creation. Use the existing exact-object Reference Field Handle
  route where supported; complete applicability and effect proof separately.
- **Conversion (#179/#183):** the 2024/25 setter now binds a discovered installed
  Conversion Type Handle and an exact live platform, revalidates the codec
  snapshots before writing, verifies class/owner and other platform fields, and
  retains the verified codec GUID for a separate exact-object Field Handle
  Preview. Focused fake-Gateway and persisted-finalizer tests prove this path.
  Native per-platform codec enumeration and actual anonymous identity shape
  still require the selected prewrite observation; multiple/unknown rows stop
  before mutation. Older arbitrary replacement/configuration remains unresolved;
  whole-Conversion donor copy is a separate existing alternative. Matching
  getProjectInfo.defaultConversion supplies the Project's default Conversion
  GUID without assuming the setter accepts Project GUIDs. See
  [the source and mapping note](../../research/conversion-plugin-placement-179.md).
- **Condition semantics (#177/#178):** unresolved mustChildOf/related-owner,
  mixed partial restriction semantics, unknown target classifiers and class
  default/controller shapes retain their original owners. Known same-object
  scalar/default/reference-presence handling is reused here, not blanket-blocked
  on missing native receipts. Class Field Handle restrictions not yet admitted
  by discovery remain an implementation boundary rather than native absence.
- **Staged provenance (#178/#179):** the durable verified-created-from selector
  currently binds an object.create root. Created plugins and recursive/list
  children need their own sealed identity continuation where required.
- **Native acceptance:** sequential owned sandbox evidence on all pinned builds
  must prove native creatability, actual host, applicable parent/platform,
  class/property/reference effects, conflict/drift refusal and preservation.
  License/setup failures remain blockers. No Fresh, Windows, full Program or
  full Non-live acceptance is claimed by this checkpoint.

Exact worker test outcomes and candidate attribution are recorded in the
handoff; generated coverage/source inventories remain integration-owner work.
