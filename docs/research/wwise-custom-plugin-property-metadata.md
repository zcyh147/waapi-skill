# Wwise custom plug-in property metadata discovery

- Date: 2026-08-24
- Scope: Wwise 2021.1 through 2025.1, WAAPI Authoring object metadata,
  Authoring plug-in XML, `.wcustomproperties`, and Sound Engine plug-in
  parameters
- Evidence policy: Audiokinetic documentation/SDK only, plus this repository's
  reflected official schemas and implementation
- Validation performed: documentation, installed SDK headers/samples, and
  repository inspection only; no Wwise process or test campaign was started

## Answer

Yes: for a property or reference that is registered in the live Wwise
**Authoring object model**, the normal path should be live discovery, not an
installed schema pack.

1. Call
   [`ak.wwise.core.object.getPropertyAndReferenceNames`](https://www.audiokinetic.com/en/library/edge/?id=ak_wwise_core_object_getpropertyandreferencenames.html&source=SDK)
   with the exact plug-in instance (`object`) when one exists, or its exact
   `classId` before creation. It returns all property/reference names for that
   scope.
2. Call
   [`ak.wwise.core.object.getPropertyInfo`](https://www.audiokinetic.com/en/library/edge/?id=ak_wwise_core_object_getpropertyinfo.html&source=SDK)
   for a returned token in the same scope. Its reflected result includes the
   canonical name, type, default, numeric range / enumeration / reference
   restrictions, dependencies, RTPC/randomizer/unlink support, display/UI
   information, and `audioEngineId`.
3. If current conditional availability matters, call
   [`ak.wwise.core.object.isPropertyEnabled`](https://www.audiokinetic.com/en/public-library/2024.1.5_8803/?id=ak_wwise_core_object_ispropertyenabled.html&source=SDK)
   for the exact object, property, and platform. Static metadata alone is not a
   complete answer to "is it enabled on this instance right now?"

This supports changing Q13's normal path to **discover live, issue a bounded
field handle, mutate, and read back**. A trusted schema pack is an exceptional
fallback for a proven reflection gap, not the default plug-in integration
mechanism.

The qualification matters: **"some value can be changed somehow" does not
imply "WAAPI can discover it."** Even the narrower statement, "every value a
third-party plug-in accepts through any WAAPI surface must be completely
reflected," is not stated as a formal Audiokinetic guarantee. The strong,
supported inference applies only when the value is an Authoring object-model
property/reference addressed through `object.setProperty`, `setReference`, or
the corresponding `object.set` field.

## What the official model exposes

### Ordinary Authoring object properties and references

The generic enumeration API accepts either a concrete `object` or a `classId`
and describes its result as "all properties and references" for the specified
object. The generic information API uses the same two scopes plus an exact
field token. This is the intended dynamic reflection surface, not merely a
static list of Audiokinetic's built-in fields.

The repository's reflected Wwise 2025.1 schemas preserve that contract:

- `skills/waapi-skill/resources/manifest/2025.1/schemas.json:5117-5167`
  contains the `object | classId` enumeration request and the all-name result.
- `skills/waapi-skill/resources/manifest/2025.1/schemas.json:5169-5204`
  contains the `object | classId` plus property-token detail request.
- `skills/waapi-skill/resources/manifest/2025.1/schemas.json:5210-5523`
  contains `audioEngineId`, default, dependencies, display, type, range,
  reference, enumeration, and supported-feature metadata.

The same two endpoints and the same basic request/result fields exist in the
repository's reflected Wwise 2021.1 schema
(`skills/waapi-skill/resources/manifest/2021.1/schemas.json:3290-3353` and
`:3355-3771`) and in every packaged lane between 2021.1 and 2025.1. The exact
nested schema has version deltas, so consumers must continue using the
configured version's reflected schema rather than assuming byte-identical
metadata across versions.

### Source, Effect, and other Authoring plug-in properties

Audiokinetic describes an Authoring audio plug-in as including an
[`XML definition of the model—that is, the plug-in's properties`](https://www.audiokinetic.com/library/2024.1.0_8598/?id=effectpluginwwise.html&source=SDK).
The official
[`Properties XML Description`](https://www.audiokinetic.com/en/library/edge/?id=plugin_xml_properties.html&source=SDK)
defines property tokens, types, defaults, UI data, restrictions, references,
RTPC support, and `AudioEnginePropertyID` mappings.

There is unusually direct evidence that the generic object APIs are the
successor for plug-in property discovery. In the installed Audiokinetic 2025.1
SDK, the generated WAAPI constants mark:

- `ak.wwise.core.plugin.getProperties` as deprecated in favor of
  `ak.wwise.core.object.getPropertyAndReferenceNames`; and
- `ak.wwise.core.plugin.getProperty` as deprecated in favor of
  `ak.wwise.core.object.getPropertyInfo`.

Exact evidence:
`/Applications/Audiokinetic/Wwise2025.1.7.9143/SDK/include/AK/WwiseAuthoringAPI/ts/waapi.ts:270-285`.
The same replacement comment is present in the locally installed official
2021.1, 2022.1, 2023.1, and 2024.1 SDK constants. The 2025.1 Authoring plug-in
host header also says the default property set is defined by the XML file and
that property names used by the host correspond to XML property names:
`/Applications/Audiokinetic/Wwise2025.1.7.9143/SDK/include/AK/Wwise/Plugin/V1/HostPropertySet.h:38-49`.

Therefore an XML-declared, registered plug-in property should normally be
discoverable live. Prefer the actual plug-in instance scope because it proves
the field belongs to that installed plug-in in the open project. Use class
scope when no instance exists yet and creation requires fields.

### `.wcustomproperties` properties and references

Audiokinetic's
[`Defining Custom Properties`](https://www.audiokinetic.com/en/library/edge/?id=defining_custom_properties.html&source=SDK)
documentation says these files add properties to named Wwise object types and
that all custom properties are loaded at project load. Its official example
contains both `<Property>` and `<Reference>` declarations, with types, defaults,
ranges/enumerations, reference type restrictions, UI information, and optional
`AudioEnginePropertyID` values. The same page lists dependencies among the
supported declaration metadata.

The documentation does not contain the literal sentence "every
`.wcustomproperties` declaration appears in
`getPropertyAndReferenceNames`." The conclusion follows from two official
contracts: the declarations are loaded as Authoring object properties, and the
generic API returns all properties/references in the chosen object scope. Treat
this as a strong engineering inference and still verify it against the live
object before mutation. A load failure, name collision, wrong `WwiseObject`
identity, or missing project reload can prevent a declaration from being
registered; the custom-property documentation explicitly describes those load
and collision conditions.

### Runtime-only parameters and opaque plug-in state

Sound Engine plug-in parameters are a different layer. The official
[`IAkPluginParam`](https://github.com/audiokinetic/WwiseIncludes/blob/master/SDK/include/AK/SoundEngine/Common/IAkPlugin.h)
interface accepts a numeric `AkPluginParamID` in `SetParam`; Audiokinetic says
that this ID corresponds to `AudioEnginePropertyID` in the plug-in XML. The
official Properties XML documentation likewise says an
`AudioEnginePropertyID`, when present, is passed to `IAkPluginParam::SetParam`.

That mapping connects an XML-declared Authoring property to its runtime
parameter. It does **not** turn every DSP variable, parameter-block member,
opaque custom-data blob, custom UI private value, or internally synthesized
state into an Authoring property. A runtime value without an Authoring XML /
object-model declaration has no object-model token, type, restriction, or
applicability record for these WAAPI metadata endpoints to enumerate.

Conversely, an Authoring custom property can exist without being exported to
the Sound Engine. Audiokinetic documents that only supported custom-property
forms are exported to SoundBanks, and that non-numeric values such as strings
are not exported. Authoring discoverability and runtime availability are
related only when the plug-in/custom-property definition explicitly binds
them.

## Does successful setting imply successful discovery?

| Meaning of "settable" | Discoverability conclusion |
| --- | --- |
| A registered field is accepted by `ak.wwise.core.object.setProperty` or `setReference` on the same Authoring object | It should be returned by object-scoped enumeration and described by object-scoped `getPropertyInfo`; this is the normal live path. Still fail closed if live reflection disagrees. |
| A registered plug-in field is supplied inside `ak.wwise.core.object.set` during Source/Effect creation | Class-scoped metadata is the available pre-creation proof; after creation, repeat against the concrete instance and read back the exact field. |
| A plug-in's own Authoring host API changes an XML property | The XML field belongs to the Authoring model, but success through the in-process host API is not itself proof that the public WAAPI route is exposed on the intended object. Confirm with live WAAPI discovery. |
| `IAkPluginParam::SetParam`, `SetParamsBlock`, game/runtime APIs, or internal DSP code changes a value | No WAAPI Authoring metadata can be inferred unless that value is also declared and registered as an Authoring property/reference. |
| A proprietary WAAPI endpoint or opaque custom-data mechanism changes a value | No generic metadata guarantee. It needs a separately reviewed closed contract or a trusted schema pack with explicit verification limits. |

Audiokinetic's public pages describe each API, but do not state a universal
bidirectional invariant such as `settable_by_any_WAAPI_surface ⇔ discoverable`.
The safe implementation rule is therefore discovery-first: a mutation field
handle is issued only after the live enumeration/detail chain succeeds. A
known raw token that happens to work is not sufficient to skip discovery.

## Current repository behavior

The repository already implements most of the desired normal path:

- `metadata_discovery.py:1-11` limits discovery to live `getTypes`,
  `getPropertyAndReferenceNames`, and `getPropertyInfo`, and explicitly refuses
  to invent aliases.
- `metadata_discovery.py:244-310` requires exactly one of object type, class ID,
  or concrete object, enumerates live names, and retrieves detail only for a
  bounded candidate pool.
- `metadata_discovery.py:400-489` resolves object-type requests through live
  `getTypes` and passes either exact `classId` or exact object identity to the
  metadata calls.
- `builders/metadata.py:100-125` and `:341-365` preserve name, type, default,
  supports, display, restrictions, dependencies, UI, `audioEngineId`, and the
  raw live row. `metadata_discovery.py:1216-1222` distinguishes references from
  properties using live type/restriction metadata.
- `metadata_cache.py:1-6` correctly treats static metadata as session/project/
  runtime-bound but excludes dynamic `isPropertyEnabled` results from caching.

There are two current boundaries to keep visible:

1. Discovery is a bounded lexical candidate finder, not a bulk dump or a
   claim that its highest-ranked result expresses user intent. It can enumerate
   up to 4,096 names but retrieves detail for a bounded candidate pool
   (`metadata_discovery.py:38-53`, `:270-310`). This is suitable for
   `find-fields`, provided the user or a deterministic exact-token match makes
   the final selection.
2. The packaged `object.createPlugin` helper currently supports Wwise
   2022.1-2025.1 and requires exact caller-supplied property names, then validates
   each requested name/type with class-scoped live `getPropertyInfo`.
   See `operation_plugin.py:1-17`, `:28-30`, and `:391-463`. It does not itself
   perform the preceding name enumeration. The general metadata route can
   provide that discovery step, but a future cohesive field-handle flow must
   bind the discovery result to plug-in creation rather than letting the Agent
   retype an unbound raw token.

General metadata discovery remains available in all five supported version
lanes. The narrower `object.createPlugin` version boundary must not be confused
with metadata endpoint availability.

## Recommended Q13 contract

Use this order:

1. Resolve an exact existing plug-in instance; if creating a new instance,
   resolve the exact registered plug-in `classId`.
2. Enumerate property/reference tokens live in that exact scope.
3. Retrieve exact metadata for the candidate selected from that enumeration.
4. If it is a property whose dependency/platform state matters, check
   `isPropertyEnabled` against the concrete object and explicit platform.
5. Issue a scope-, Wwise-build-, project/session-, token-, type-, restriction-,
   and metadata-digest-bound field handle.
6. Construct the closed mutation from the handle and explicit user value.
7. Read back the same field from the created/modified GUID. For references,
   validate the target GUID/type against live reference restrictions.
8. If enumeration omits the field or detail is incomplete, stop with a
   capability gap. Only then consider a separately installed, versioned,
   trusted schema pack; it must not convert an Agent's same-turn guess into a
   trusted field.

This leaves the requested custom-plug-in opening without restoring raw
property-token input as the normal Agent interface.

## Unproven boundaries

- No official source found states an exception-free theorem that every value
  changed by any third-party WAAPI extension is reflected by the generic object
  metadata APIs.
- No live third-party custom plug-in or `.wcustomproperties` fixture was probed
  in this research task, by design. The conclusion is documentation/schema
  evidence, not new executable evidence.
- A plug-in can enforce semantic relationships beyond XML metadata. Successful
  `getPropertyInfo` proves the declared model, not all proprietary validation
  performed by plug-in code.
- Object Store inner property sets, opaque custom data, custom UI state, and
  proprietary endpoints need separate inspection. Do not assume that the
  default plug-in object's metadata scope covers them.
- The live API gives scoped applicability and dependency metadata, not one
  universal `applicableObjectTypes` field. Current enabled state needs the
  concrete object/platform check.
