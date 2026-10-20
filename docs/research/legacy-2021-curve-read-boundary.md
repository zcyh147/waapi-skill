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

## R50 original-only read: exact native failure

Frozen `cbd067c2a4ba230a49cfa090512a5a505ad3c582` ran exactly once on
Console2021.1.14.8108. Evidence root:
`/Users/xiye/Documents/Git/waapi-skills/.waapi-skill-state/full-coverage/r50-original-owned-read-cbd067c2-2021-r1/`.
Original `category.jsonl` records final v3/node/category FAIL; collection is
incomplete and business verification false. Eight public reads made zero
transactions or writes. All68 source file contents/size/mtime and full tree,
project mtime and2211 tracked files stayed unchanged; owned processes closed and
the failed sandbox remains quarantined. No old project was opened or replayed.

The first Source-list expression `from object "{95DDA32B-B666-4269-A54C-5ABF4E201C99}" select @RTPC take 8`
failed with `ak.wwise.query.invalid_query`, message `Unknown property RTPC (61)`.
All18 Source scalar fields were observed first, but the RTPC/LFO/Curve metadata
and reference hops were never reached. This establishes rejection of that exact
Source hop, not API-wide absence of owned lists or Curve points. Do not rerun it
or let it block an independent exact-GUID read.

## Successor: known exact objects first, documented reference hop last

`test_legacy_original_source_owned_read_console_diagnostic` reuses the existing
workflow lifecycle/config/archive, with **zero setup/copy writes**. The
successor is based on integration17c0 and preserves the original cbd067 pin and
native evidence. It must be reviewed before a separate native authorization.

1. Verify the exact Console build and fresh Synth type. Read only the original
   Source identity/class at `{95DDA32B-B666-4269-A54C-5ABF4E201C99}`; its18 fields
   are already proved by R50 and are not rediscovered for this narrower case.
2. Bind RTPC `{CE99046D-D354-422D-A7BB-F1305FF00B2F}` by exact-ID read, require
   class1441808 and owner=that Source before metadata. This GUID/class/owner edge
   was independently observed before/after the ae7 attempt; it is not derived
   from the rejected list accessor. Read its complete live metadata list,
   returned detail selections and every publicly readable field in8-field pages.
3. Independently bind LFO `{E323F786-253F-48C6-86B9-AB0335804E9F}` by exact GUID,
   class4194320 and owner=that RTPC. Read its actual complete metadata and fields.
4. Independently bind Curve `{0B357DC6-5FE7-4E50-9C31-23CDE7F34307}` by exact GUID,
   class917520 and owner=that RTPC. Read its actual complete metadata and fields.
   No @Curve hop precedes or replaces this observation: ParamControl's matching
   docs/names do not establish that reference. No curve-points or guessed @Points
   getter is supplied.
5. Persist all known-object observations, then attempt only the documented
   `select @ControlInput` reference hop on the exact RTPC, max2, with ordinary
   business identity/class/owner/parent/notes projection. Require the returned
   row to agree with the independently read LFO. Its SDK reference semantics are
   known; this particular2021 public/native hop remains unproved. Its failure
   must preserve the already collected Curve metadata and stop without another
   spelling, setup or copy.

Source RTPC membership is **not enumerated or declared complete**. Unknown-kind
metadata values, including ControlInput's retained empty native type/restriction,
are recorded in `metadata_unreadable_fields`; no Reference restriction or scalar
type is fabricated to force `--include-field`. A canonical reference hop proves
only that edge, not mutation applicability. Complete diagnostic collection keeps
business category blocked, diagnostic_only=true/business_effect_verified=false;
Curve points, copied graph, whole-plugin behavior and history remain unresolved.

The read-only mode permits only status, query-object and metadata types/list/detail.
The Gateway owns custom projection from live metadata, and owns advanced URI,
projection and final take. Existing128-call,1MiB-per-reply,16MiB-total-reply,
256KiB-receipt,64MiB-archive/512-native-file limits stay unchanged. Metadata pages
contain at most64 names and use returned selections; custom fields use the
existing8-meaning limit. Fakes prove routing, genuine field paging, exact-binding
class/owner rejection before metadata, and a documented-hop rejection with zero
writes/fallback. They never prove native queryability or field availability.

## Separate future membership candidate, not dispatched by this diagnostic

The matching WAQL reference documents custom-object owner selection/filtering
(lines227–236 of the retained text), chained object/value accessors (281–284),
and GUID equality (305–310). Thus an owner.id equality filter has explicit
language semantics; it is not an invented property name. The pinned live type
catalog reports ParamControl/class1441808 and Curve/class917520. `RTPC` is an
observed row type, not a catalog spelling to substitute for ParamControl.

A separately reviewed membership observation could first confirm fresh
`metadata types --meaning ParamControl --meaning Curve` selections, then test
bounded advanced queries using those exact catalog names and owner GUIDs:
`from type ParamControl where owner.id = "{95DDA32B-B666-4269-A54C-5ABF4E201C99}"`
and `from type Curve where owner.id = "{CE99046D-D354-422D-A7BB-F1305FF00B2F}"`.
The Gateway supplies final take and fixed projection. These are source-backed
candidates, **not native-proven membership reads**: catalog metadata does not
certify from-type queryability or enumeration of internal objects. Require the
known exact member as a positive control, matching classes/owners, unique IDs,
complete projection and no result-limit truncation. Empty results while a known
exact member resolves cannot certify an empty list. A rejected catalog generator
must remain that precise failure; do not try alternate aliases or infer absence.
Even a successful RTPC/Curve query would certify only that scoped class, not the
entire Source-owned closure. No such query is added to this successor and no new
native launch is authorized by this note.


## R52: fixture-scoped saved-copy diagnostic (native pending)

R51's accepted 28-read result proves the documented ControlInput hop and exact
RTPC/LFO/Curve owner/class frames, not a points getter. Its immutable evidence is
`/Users/xiye/Documents/Git/waapi-skills/.waapi-skill-state/full-coverage/r51-exact-owned-read-90c1089-2021-r1/diagnostic-result.md`.
The next diagnostic reuses the existing collector and lifecycle, with four
separate public transactions: baseline `project.save`, empty SFX Sound setup,
Source-only copy, final `project.save`. Matching 2021.1.14 SDK/reflection and
closed `request-schema` snapshots are `/tmp/waapi-r51-copy-save-primary/`.
Save's schema digest is
`3ba730f37f73a10ca133846b3604783903adc088d29bc8cfce9b414568c2c89e`;
its public continuation is zero-input, not a 2025 auto-check-out declaration.
The existing `_save_sandbox_project` follows preview/confirmation/one execution/
verification; result-schema checking alone never establishes saved state.

Before each Save, an exact Project GUID query with file-path must equal the owned
sandbox project; status.path is only the Wwise hierarchy path. Only exact public
Work Unit/file-path observations select the owned sandbox WWUs.
`ConsoleModelImageIndex` and existing file observations retain each image once,
inside the unchanged aggregate archive ceiling. XML guards remain 8 MiB/file,
no DOCTYPE, 32768 nodes and depth64. The fixture-only oracle compares the entire
Source subtree and original preservation, including unknown attributes, text,
all fields and ordered Curve PointList, with a bijection for the four known
owned declarations. Other GUID/reference changes remain exact or fail closed;
new/ambiguous/missing owned declarations are rejected. The current fixture has
no ObjectRef nodes; future native evidence must not imply that external or
internal ObjectRef remapping was exercised. ControlInput is serialized as the
actual nested Custom ModulatorLfo and independently checked through the
R51-supported canonical reference hop.

Every serialized declaration ShortID must equal its independent live `short-id`
read (the matching fixed objectReturn accessor); its original/copied values are
recorded explicitly. They are classified as live-bound identity values without
requiring equality or change. Curve has no serialized ShortID in the retained
fixture; adding one only to the copy is an unexplained difference. Independent
exact copied GUID/class/type/name/notes/owner reads and actual Boolean IsVoice/
complete childsets for both Sounds remain mandatory. No R51 metadata detail
campaign or Source-field paging is duplicated to populate the receipt.

The new node is `test_legacy_source_only_copy_saved_graph_console_diagnostic`.
Fake protocol completion and pure XML controls do not prove native copy. The
category remains diagnostic-only with `business_effect_verified=false`; the
production verifier and its authority/history boundary are unchanged. No user
project is implicitly saved, no original quarantine is opened, and this test
oracle is never a runtime filesystem fallback. Native execution requires its
own reviewed frozen candidate and explicit authorization.
