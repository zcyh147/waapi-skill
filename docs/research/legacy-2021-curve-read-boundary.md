# Wwise 2021.1 original Source owned-state read boundary

The matching SDK and reflection do not document a generic Curve-points getter
for 2021.1. They do **not** establish that every native object accessor lacks
such a getter. The public `curve-points` output is unavailable in 2021.1, and
the existing native evidence contains no read of this retained RTPC's Curve
points. Do not claim native absence or complete Source-copy preservation.

## Exact source basis

Primary source: `/Applications/Audiokinetic/Wwise2021.1.14.8108/SDK/Help/WwiseSDK-Windows.chm`.
The selected pages identify SDK 2021.1.14–Windows. This is static documentation,
not native Windows evidence. Exact HTML extracts and their manifest are retained
at `/tmp/waapi-r50-curve-2021-primary/`.

| SDK member | SHA-256 |
| --- | --- |
| `ak_wwise_core_object_get.html` | `14887bfbabc3580b02d655be3e81be220a731a588c8a009ac1fd536527225c44` |
| `waql_reference.html` | `87b10aecdd13083c0a2d75fb0659119fbe08ba54ea5bfa85f041576033074ac4` |
| `waapi_query.html` | `48b12b73e1d25a4cdf878b69e51e3e89a5ded1bf7297b5e8b72a5846a6bdf62d` |
| `wwiseobject_curve.html` | `eed5da8237c2b2281e4933505d0c8a15b8bbcdde3840b985e578d2a78e4841bc` |
| `wwiseobject_paramcontrol.html` | `6c9d0b8b83998caec78590b2979b2cda2957c627f9c9560eb835e5bfd3b6e0e3` |
| `wwiseobject_modulatorlfo.html` | `8c7bd9e885119eeff3e71ddf1c59ecefae5306e978ff260f7a3578fd4dc3ab66` |
| `ak_wwise_core_object_curvechanged.html` | `1a7c8e60af2e0b067196124a1b05c27e4be74199d4ebe354621554d67e278edd` |
| `ak_wwise_core_object_getattenuationcurve.html` | `524b01651bcd475c6bbeb0fa6626aa301814b42d2ddaf49de507b11f34b28fce` |

Curve class917520 documents only `Flags:int32`; ParamControl class1441808
documents Color, ControlInput and OverrideColor. It does not document the modern
PropertyName/Curve pair. ModulatorLfo class4194320 documents ten fields, including
Color/OverrideColor and eight LFO/scope fields. The fake collector uses these
actual names/types; its values are fixture observations, never production defaults.

The matching `resources/manifest/2021.1/schemas.json` object.get schema permits
WAQL. Its deprecated transform.select permits hierarchy relationships only.
`definitions.json` → documents.waapi_definitions.json.definitions.objectReturn
has no fixed points property. Its generic property/reference/list projection
patterns are not a closed enumeration of every native accessor, so this omission
alone cannot prove that an undocumented inline Curve value is impossible.

The SDK's WAQL reference documents direct/reference selection and the owner of
custom objects. Its object.get/query return descriptions document scalar values,
references and reference traversal; neither selected page names a points getter.
The SDK's getAttenuationCurve applies to an attenuation object and fixed
attenuation roles; it is not a getter for an arbitrary RTPC-owned Curve.
The reflected profiler.getRTPCs observes runtime parameter values. curveChanged
reports change events and has no documented initial snapshot or points payload.
Neither substitutes for a complete read-only Curve snapshot.

## Existing implementation and evidence limits

`wwise_waapi/object_query_outputs.py` derives the `curve-points` output's version
availability from reflection. Offline 2021.1 `query-schema --output curve-points`
reports unavailable, with 2022.1–2025.1 supported. The exact schema snapshots are
`/tmp/waapi-r49-owned-read-plan-evidence/`. This is a packaged read boundary.

`operation_registry.py::_read_rtpc_rows_with_evidence` first reads the native
owner @RTPC list, then resolves member GUIDs. Its complete snapshot requires
@PropertyName, @ControlInput and inline @Curve.points. That internal requirement
is not independent proof of a matching 2021 getter, nor permission to supply
native return fields through the public query interface. The modern RTPC
acceptance collector explicitly excludes 2021 construction and uses the later
curve-points output. Do not transfer its evidence to this lane.

The immutable ae7 Console2021.1.14.8108 attempt in the main repository's
`.waapi-skill-state/full-coverage/r48-legacy-copy-ae7a6b4b-2021-r1/`
observed Source class9699330, all18 Source scalar fields and the original
RTPC/LFO/Curve identities with owner edges. Source descendants were empty despite
those known owned objects. `bounded-observations.json` identifies every archived
reply/native file; no RTPC metadata, inline Curve value or copied owned bindings
were captured. Equal Source scalar pages therefore do not settle this question.

An earlier matching native observation already resolves another Sound-owned
RTPC and its complete three-name inventory. Its exact candidate is
`8e9b9f173e71a80126600683f8d12371cb5bf76c`; original report:
`/Users/xiye/.codex/worktrees/waapi-authoring-layout/waapi-skills/.waapi-skill-state/full-coverage/rtpc-2021-representation-8e9b9f17-r1/pytest/gateway-workflows-2021-10/state/rtpc-2021-representation-diagnostic.json`
(SHA-256 `05458382bbff8e521b8e216202938e1a852a7a6414e5f653dcbda4b245bff8f7`).
Its native ControlInput metadata has empty type and empty restriction, despite
the SDK describing a reference. The public custom-field compiler correctly
leaves that field unresolved; do not invent a reference restriction in the fake.
This evidence is reused without rediscovering its Sound/RTPC facts. It contains
no Source-owned membership, ControlInput hop or Curve points observation.

Static inspection of its failed quarantine found neither the new Sound nor new
Source GUID in all65 saved project XML files. The 98-entry full-tree snapshot
remained identical; proof is `/tmp/waapi-r49-quarantine-persistence.json`.
The original quarantine stays unopened and immutable. It cannot supply the
unsaved copied graph through a clone. Original run ERROR and accepted8e2 remain
preserved.

## Next bounded observation

`test_legacy_original_source_owned_read_console_diagnostic` reuses the existing
workflow lifecycle and diagnostic archive. It performs **zero setup/copy writes**:

1. Verify the exact Console build and fresh Synth type; read the original Source
   GUID `{95DDA32B-B666-4269-A54C-5ABF4E201C99}` and all live-discovered fields.
2. Through public `query-object --advanced-waql`, read that Source's fixed
   `select @RTPC` hop, max8. Require its retained known member GUID and owner.
3. Read that RTPC's complete live `metadata list`, its returned detail selections,
   and certified exact-ID field meanings through `--include-field`. Record each
   unknown-kind field explicitly as unreadable through that public projection;
   do not silently discard it or fabricate metadata. Do not require the
   undocumented modern PropertyName/Curve fields or invent them.
4. Use the documented reference selection `select @ControlInput`, max2, to reach
   the known LFO even when ControlInput's live metadata is untyped. Read its
   identity/owner, complete metadata and every publicly readable field; retain
   explicit unknown-kind fields. A canonical reference hop proves that edge,
   not mutation applicability or a missing property type.
5. Read the fixed RTPC `select @Curve` hop, max2, then that Curve's exact identity,
   owner, complete metadata and discovered fields. No `curve-points`, guessed
   @Points or raw projection is accepted. The pending native observation must
   establish whether these exact 2021 hops and metadata reads work.

`gateway.py::_bind_query_custom_fields_from_live_metadata` owns property/reference
accessor compilation. The advanced layer owns object.get, projection and final
take; it has no caller custom projection. If a native hop rejects or metadata
cannot express a value, archive the exact first result and stop without retry,
alternate spelling, setup or copy. A complete diagnostic protocol keeps its
business category blocked and still excludes points,
copy mapping, business verification and history coverage. If Curve metadata has
only Flags, the inline @Curve getter remains unresolved; it must not be declared
absent from that result alone. Any next proposed closed read seam needs matching
source evidence and separate review, not a raw escape hatch.

The collector keeps the existing128-call,1MiB-per-reply,16MiB-total-reply,
256KiB-receipt,64MiB-archive/512-native-file bounds. Fields use the existing
8-meaning discovery page limit; metadata uses public64-name pages and returned
selections. The read-only mode rejects every Gateway command outside status,
query-object and metadata types/list/detail. Fake controls cover genuine
18-field Synth and ten-field LFO paging, real v3 category validation, and a
first-hop rejection with zero writes/fallback. They prove routing and evidence
handling only. No native launch or wider production copy verifier is authorized
by this note.
