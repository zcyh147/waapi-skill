# Five-version CRUD interface and evidence audit — 2026-09-13

## Scope and evidence boundary

Read-only audit of `main` ancestry candidate
`2c714912e8383538290dd46fd61af56526c8e4fe`, on working branch
`codex/harden-batch-field-diagnostics`. The pre-existing uncommitted Gateway
diagnostic changes and its regression test were not changed by this audit.
No Wwise, Fresh Agent, network client, test gate, project mutation, old Draft,
or transaction was started/replayed. Local registry imports and packaged JSON
inspection are static inspection, not test passes.

The audit concerns the version partition and existing evidence for creation,
ordinary field edits, bulk edits, plug-ins, RTPCs, import, lifecycle edits,
randomizer, property paste and State properties. It complements the separate
public-entrypoint/call-chain audit; an internal `OperationSpec` native token is
not by itself an exposed Agent parameter. The public contract must be checked
through the operation-local business contract or exact-URI business contract.

## Version partition

`yes` means an implemented packaged public lane, not new live verification.
`—` means the reviewed lane is explicitly absent in that version, not an
unexplained parameter-matching failure.

| Operation family | 2021.1 | 2022.1 | 2023.1 | 2024.1 | 2025.1 |
| --- | --- | --- | --- | --- | --- |
| `audio.import`, `object.create` | yes | yes | yes | yes | yes |
| `object.copy/delete/move/setName/setNotes` | yes | yes | yes | yes | yes |
| `object.setProperty/setReference` | yes | yes | yes | yes | yes |
| `object.set`, `object.createPlugin`, `object.setRTPC` | — | yes | yes | yes | yes |
| `object.setLinked`, `object.isLinked` | — | — | yes | yes | yes |
| `object.pasteProperties`, `object.diff` | — | yes | yes | yes | yes |
| `object.setStateGroups/setStateProperties` | — | — | yes | yes | yes |
| `object.setRandomizer/setAttenuationCurve` | yes | yes | yes | yes | yes |

Sources:

- [Graph contracts](../../skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py#L27)
  explicitly restrict bulk `set`, plug-in construction and RTPC construction
  to 2022 onward. Their native `ak.wwise.core.object.set` URI is absent from
  [2021 functions](../../skills/waapi-skill/resources/manifest/2021.1/functions.json)
  and present from the [2022 reflection](../../skills/waapi-skill/resources/manifest/2022.1/functions.json).
- [Metadata contracts](../../skills/waapi-skill/wwise_waapi/object_metadata_business_contracts.py#L17)
  restrict platform link changes to 2023 onward while preserving all-five
  ordinary property/reference edits.
- [Lifecycle contracts](../../skills/waapi-skill/wwise_waapi/object_lifecycle_business_contracts.py#L63)
  admit all five versions. [Core contracts](../../skills/waapi-skill/wwise_waapi/core_business_contracts.py#L10)
  enumerate the remaining exact-URI version lanes.
- `describe_operation(...).supported_versions` was inspected for all 13 named
  operations in the first five table rows; results agree with these contracts.
  The five `resources/manifest/<version>/functions.json` files were separately
  inspected for every `ak.wwise.core.object.*` URI. None contains an ordinary
  `object.reset*` URI. SoundEngine `resetRTPCValue` is runtime control, not a
  missing Authoring CRUD property-reset lane.

### Complete reflected Core object URI union

The five `functions.json` files contain **23 unique** `ak.wwise.core.object.*`
URIs. This inventory is exhaustive for that exact namespace, not all
CRUD-related namespaces. Version numbers abbreviate `202x.1`.

| URI suffix | Present versions | Public routing family examined |
| --- | --- | --- |
| `copy` | 21–25 | Named lifecycle Draft |
| `create` | 21–25 | Named graph Draft |
| `delete` | 21–25 | Named lifecycle Draft |
| `diff` | 22–25 | Core business bounded read |
| `get` | 21–25 | Business query / separately bounded advanced read |
| `getAttenuationCurve` | 21–25 | Fixed structured read |
| `getPropertyAndReferenceNames` | 21–25 | Fixed metadata read |
| `getPropertyInfo` | 21–25 | Fixed metadata read |
| `getTypes` | 21–25 | Fixed type discovery read |
| `isLinked` | 23–25 | Core business bounded read |
| `isPropertyEnabled` | 21–25 | Fixed metadata read |
| `move` | 21–25 | Named lifecycle Draft |
| `pasteProperties` | 22–25 | Core business mutation Draft |
| `set` | 22–25 | Named graph Draft; plug-in/RTPC materialization |
| `setAttenuationCurve` | 21–25 | Core business mutation Draft |
| `setLinked` | 23–25 | Named metadata Draft |
| `setName` | 21–25 | Named lifecycle Draft |
| `setNotes` | 21–25 | Named lifecycle Draft |
| `setProperty` | 21–25 | Named metadata Draft |
| `setRandomizer` | 21–25 | Core business mutation Draft |
| `setReference` | 21–25 | Named metadata Draft |
| `setStateGroups` | 23–25 | Core business mutation Draft |
| `setStateProperties` | 23–25 | Core business mutation Draft |

Route classification also references the reviewed-special URI set in
[surface policy](../../skills/waapi-skill/resources/native_surface_policy.json#L38)
and Core/business contracts above. Fixed read routes are inventoried here but
their complete query compiler is reviewed separately by the main audit.
`audio.import` is adjacent and examined above. `audio.importTabDelimited` is a
user-owned artifact contract and should not automatically be classified as a
native property escape merely because its artifact contains property columns.
This audit does not claim every SoundBank, Switch/Blend assignment or other
namespace has been deeply re-audited.

Do not add a 2021 `object.set` fallback or simulate unsupported RTPC operations
as part of this interface repair. A valid 2021 scalar Action edit can still
use its ordinary `object.setProperty` lane; this does not make native batching
or RTPC construction available there.

## Real version differences already represented

1. **Plug-in topology:** 2022 Effects occupy the first proven-empty fixed
   `Effect0..Effect3` reference; 2023 onward appends `EffectSlot` and validates
   its Effect binding. See [operation registry](../../skills/waapi-skill/wwise_waapi/operation_registry.py#L2534).
   One shared table must not flatten this topology distinction.
2. **Media in `object.set`:** the graph compiler only admits media import in
   2023 onward and directs 2022 to `audio.import`. See
   [object graph compiler](../../skills/waapi-skill/wwise_waapi/object_graph_business.py#L240).
3. **Source control:** import checkout options are 2023 onward, with explicit
   earlier-version rejection. See [import compiler](../../skills/waapi-skill/wwise_waapi/audio_import_business.py#L125).
   Lifecycle contracts likewise remove unavailable source-control flags from
   disclosure ([contract](../../skills/waapi-skill/wwise_waapi/object_lifecycle_business_contracts.py#L78)).
4. **2025 hierarchy:** the five-version real lifecycle tests select Containers
   rather than Actor-Mixer Hierarchy in 2025. This is a versioned object/layout
   difference, not evidence of a need to re-reflect UI APIs
   ([test](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L2381)).
5. **Native schema differences are not automatically missing functionality:**
   for example, 2024/2025 `object.create` schemas add `id`, but the surface policy
   deliberately rejects caller-assigned internal GUIDs
   ([policy](../../skills/waapi-skill/resources/native_surface_policy.json#L1287)).

All five reflected `getPropertyInfo` schemas retain `classId/object/property`
inputs and name/type/default/display/restriction/support/dependency results.
All five `setProperty` and `setReference` schemas retain their respective
object/platform/field/value inputs. Their full schema JSON differs across
versions, including descriptions/references; same top-level keys are not proof
of identical value semantics. Use each version's actual schema and live field
metadata, not a hash or prior-version copy, to validate a new mapping.

## Action Fade Time / Delay: confirmed gap versus missing evidence

The domain already promises stable unit-bearing fields
([CONTEXT](../../CONTEXT.md#L29)). `COMMON_BUSINESS_FIELDS` lists
`fade_time_ms` and `delay_ms`, and the common validator accepts finite,
nonnegative millisecond numbers
([declarations](../../skills/waapi-skill/wwise_waapi/business_declarations.py#L82),
[validation](../../skills/waapi-skill/wwise_waapi/business_declarations.py#L1587)).
Repository runtime search found no invocation of this common normalization
function: defined validation is not evidence that public operations use it.
But the graph operation's actual fixed field map omits both
([contract](../../skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py#L18)).
Their presence in a generic vocabulary therefore does not prove public
materialization, native conversion, preview or verification.

The existing bulk Action test intentionally accepts both `Fade Time`/`Delay`
through `--field-meaning-value` and non-fixed `fade_time`/`delay` through
`--field` ([test](../../tests/unit/test_object_graph_business_gateway.py#L1575)).
It uses the file's default fake 2025 runtime, not a five-version real Action
metadata capture. The current diagnostic patch adds a fake 2024 failure test;
that also is not live evidence. This illustrates why passing tests can
perpetuate the inconsistent interface rather than detect it.

Search of the packaged `resources/semantic` and `references/semantic` trees
found no `FadeTime`/`Delay` field-level source records. The object-type index
records Action as a type, not its full property metadata. This audit has not
established a complete five-version snapshot of Action names, exact units,
restrictions or ActionType-dependent enabled state. The reported successful
2024 demonstration proves that concrete case, not universal five-version
Action applicability.

Therefore do not publish a five-version fixed Action field table by assuming
all metadata is identical. Reuse any original sealed Action metadata if found;
otherwise obtain only the missing per-version evidence. These are ordinary
Core metadata/readback functions already reflected by Console in every lane.
Matching Console and disposable Action fixtures suffice unless a concrete
host discrepancy is observed. Opening five Authoring applications or refreshing
the complete Authoring capability inventory is not presently justified.

## Adjacent field-taking contracts

- `object.setProperty`, `setReference` and `setLinked` require a bound field
  handle in their mutation declaration, not a field meaning
  ([metadata contracts](../../skills/waapi-skill/wwise_waapi/object_metadata_business_contracts.py#L23)).
- `object.setRTPC` requires an object-bound property handle and bound control
  input; `createPlugin` uses live type handles and class-scoped field handles
  ([graph contracts](../../skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py#L56)).
- `setRandomizer`, `pasteProperties` and `setStateProperties` use bound field
  handles/lists, and `setStateGroups` uses bound StateGroup object handles
  ([core contracts](../../skills/waapi-skill/wwise_waapi/core_business_contracts.py#L25),
  [compiler](../../skills/waapi-skill/wwise_waapi/core_business.py#L462)).
- Import already compiles `volume_db` to the native `Volume` field internally
  ([compiler](../../skills/waapi-skill/wwise_waapi/audio_import_business.py#L483)).

These observations show usable existing mechanisms; they do not certify every
runtime handle check. The complementary call-chain audit must inspect scope,
version, metadata revalidation and any alternative Gateway ingress. Repair
should reuse these mechanisms rather than add another field-authority store.

In particular, an existing import Gateway test explicitly passes
`draft-bind-field --class-name Sound --token CustomGain`, expects success, then
uses the resulting handle
([test](../../tests/unit/test_audio_import_business_gateway.py#L543)). Thus a
handle-shaped final declaration does not prove its earlier selection step is
closed. The main audit independently identified this live raw-token binding
path; this test is evidence of the current intended input, not proof that the
Agent no longer needs native tokens.

All five reflected `getPropertyInfo` schemas expose enum entries with both
`displayName` and the underlying `value`. The shared field restriction
normalizer retains only `value` as `enum_choices`
([normalizer](../../skills/waapi-skill/wwise_waapi/business_declarations.py#L1694)).
This is a cross-version disclosure limitation, not an absence in older WAAPI.
Preserving readable enum labels can be tested against existing five schemas and
fake metadata; it does not initially require another five-version Authoring
capture. Label uniqueness and value binding must remain strict, especially for
plugin-defined enums.

## Historical evidence, kept separate from this audit

The [RTPC/CRUD repair record](rtpc-crud-readback-audit-2026-09-13.md#L50)
identifies frozen candidate `a18110c8d457ffc1b843110c3cbd6bf3633fd750` and
five sequential macOS Console runs, each reporting **3 passed / 24 deselected**:
2021.1.14.8108, 2022.1.19.8584, 2023.1.19.8928, 2024.1.13.9056,
2025.1.7.9143. That is a historical record, not rerun evidence at this audit's
HEAD, not Fresh Agent and not a complete CRUD parameter matrix.

The tested workflows are visible in
[lifecycle](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L2377),
[property/reference](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L2607),
and [RTPC/list lifecycle](../../tests/destructive/test_gateway_workflow_transaction_matrix.py#L3027).
2021's RTPC case passes its unsupported-version assertion, not RTPC creation.
Property/reference checks include Volume, OutputBus and null Attenuation;
later versions include unlink. They do not provide Action Fade/Delay proof.
The same historical report documents empty RTPC/list, Effect ownership and
null-reference issues already repaired; they should not be rediscovered as
new defects solely because older tests had weak fixtures.

## Bounded repair and cheap validation proposal

1. Align all fixed-field declarations with one reviewed shared definition of
   semantics, applicable object kinds, units and supported version lanes.
   A shared definition can have explicit version deltas; do not duplicate five
   independent prompt-oriented tables or expose raw native tokens.
2. Add Action duration fields only once their exact mapping and applicability
   have evidence. Keep 2021 single-field edits distinct from 2022+ bulk edits.
   Unknown fixed names must reject, not enter the dynamic discovery path.
3. Keep long-tail field discovery separate from write selection. Batch writes
   should consume existing scope-bound field authority, retaining atomicity,
   rather than perform a fuzzy field-meaning decision as part of declaration.
4. Before any expensive run, add all-five program assertions for availability
   boundaries and supported-lane tests for declared fixed field -> materialized
   native field/value -> preview. Test wrong type, negative/nonfinite duration,
   units, unsupported version, wrong-scope/stale handles, duplicate fields,
   ambiguous discovery and unchanged Draft bytes on failure.
5. Preserve the existing pure Program gate and proportionate Non-live gate.
   Real evidence, only if mapping semantics are newly introduced and unproven,
   should be a short per-version Console test against disposable Actions, not
   another weather import or six-scenario Fresh integration campaign. A narrow
   Fresh probe would concern changed Agent routing only; it grants no five-
   version execution credit and should not replace deterministic regressions.

The version evidence points to an interface consistency repair, not a reason
to replace the Gateway, Draft state store or transaction authorization model.
