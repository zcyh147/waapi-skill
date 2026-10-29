# v1.1 inventory source review

This review reconciles the approved repair spec (#163) with current public
contracts before regenerating the interface-depth and branch-audit artifacts.
It does not promote a declared route, selector mapping, or historical test into
current branch execution credit.

## Reviewed semantic changes

| Area | Reviewed change | Contract boundary / evidence |
| --- | --- | --- |
| Connection selection (#165) | Live commands and Drafts use explicit persistent config; root host/port flags and connection environment overrides no longer select the endpoint. Version flags are offline inspection only. Persisted Draft/transaction bindings reject endpoint/version/config-path drift. | `test_gateway_connection_binding.py`; root parser flags must be sealed as well as subcommands. |
| Metadata discovery (#166) | Paged complete enumeration and exact detail selection supplement lexical discovery. Page and selection locators are Gateway-derived, read-only and scope-bound; they do not authorize mutations. Full metadata and units remain disclosed through the exact selection path. | `test_metadata_selection_gateway.py`, `test_metadata_discovery_gateway.py`, `metadata_discovery.py`. |
| Conditional fields (#167) | Reference prerequisites are derived from reviewed metadata; atomic object.set activation differs from separate confirmed prerequisite edits on object.setReference. Unsupported expressions/cycles/conflicts remain fail-closed. | `test_conditional_reference_gateway.py`; `tests/ATTENUATION_NATIVE_ACCEPTANCE.md` distinguishes all-five override activation from 2025.1-only native false-routing evidence. |
| GameParameter creation (#168) | Reviewed class-scoped Min/Max prerequisites may use matching live built-in-parameter defaults in one creation call. Arbitrary classes and dependency grammars retain the staged boundary. | `new_object_defaults.py`, `test_gameparameter_class_fields_gateway.py`; public native candidate `90018ae0` has five-version evidence for Min=-12/Max=36/InitialValue=7. |
| ShareSet creation (#169) | WorkUnit child placement is separate from owner Effect/Source topology, with live Type Handles, target preflight, result binding and independent verification. | `operation_plugin.py`, `test_plugin_shareset_gateway.py`; 2022.1–2025.1 public native candidate `df8e0610`. 2021.1 remains a packaged boundary; the classic name encoding failed, and alternative native topology is unresolved. |
| Recovery (#170) | Gateway-owned failure state determines whether a bounded read/discovery or declared correction is safe. Retryability must not be inferred from a generic command name or successful metadata read alone. | `recovery.py`, `test_policy_recovery_gateway.py`; unknown mutation outcomes remain distinct from failures proven before write. |
| Persistence (#171) | Ordinary project edits and generated outputs are retained. Resource-pair cleanup, UI registration inverse relationships, terminal host safety facts and non-reversibility remain explicit. Historical artifacts retain their hashes and final agent_result. | `transaction_cleanup.py`, `test_persistent_project_cleanup_gateway.py`, existing UI/paired/terminal regressions. |
| Compact discovery | After successful object.set field discovery, the repeated discovery menu points to the existing exact draft-inspect continuation. Full returned metadata and both declaration routes remain available, under the unchanged 7000-byte regression. | `test_object_graph_business_gateway.py::test_object_set_discovers_two_business_field_meanings_in_one_revision`. |

No reflected native URI was added or removed by these repairs. Later positive
ShareSet evidence does not erase the failed 2021.1 probe or the original frozen
business baseline. A normal unsupported public response is not native
unavailability evidence.

## Audit-tool corrections included in this reconciliation

The parser seal now records root options as a separate `<root>` contract.
Previously it covered subcommands only despite its all-public-flags wording.
The focused regression proves both offline version aliases are present and
removed root host/port flags are absent; business config and execution tests
remain responsible for semantic eligibility.

A selector policy now joins a schema occurrence only when its full reflected
schema digest matches the policy's declared version/profile schema. Equal URI
and JSON pointer alone are insufficient. A differing overlay retains an explicit
`profile_schema_mismatch` finding instead of inheriting a Console disposition.
The occurrence index and expected profile hashes are checked for drift. Residual
groups use each occurrence's schema digest, not a union of potentially different
profile schemas.

Metadata `page` and `selection` values are reviewed as Gateway-derived locator
values in fixed-command ownership accounting. They remain distinct from
caller-authored stable scalars and mutation Field Handles.

## Regeneration rules

Update the reviewed source-contract hashes only after the final runtime merges.
Use the existing `generate_interface_depth_inventory.py` producer and its
`--check`, followed by `branch_coverage_audit.py` and its `--check`. The branch
checker compares the renewed review seals directly with current registries.
`--require-complete` must continue to exit 2 while unproved business alternatives
remain, even when every generated artifact is reproducible.

The before/after source seals and exact structural deltas are recorded with the
completed regeneration below. Functional PASS counts belong to actual completed
runs, not this source review.

## Completed source-seal comparison

Runtime review base: `4dd1fa24`. The source review leaves the reflected native
surface identity unchanged. The continuation hash covers declared command
contracts and query layers, not every dynamically returned phase projection;
those retain separate Gateway regressions and branch-audit source digests.

| Seal | Previous reviewed value | Reconciled value |
| --- | --- | --- |
| `gateway_parser_sha256` | `41e31e13abb6f5e907296ad877755879d61afbf0114c6d49f80d84c358b1583e` | `7f47db965914bc7af6d2947742fc0e2a67d9bb3582f281b72e0d829573d09440` |
| `operation_contract_sha256` | `5e937223e22489a6619669834455091ba4eacf56a975d3eae3f57c048d9d0bca` | `206b88bf1d1810dbe876745c0c952208b965b92b0e74d69b3ba93878e0243617` |
| `public_continuation_sha256` | `a8db4713bb16a7a62a944ffbc15b9e63e6892fb6581cd73e600a52151f8ac8fc` | `2904c6b6e9f45047ba553e786cf3cf4f2424a54edbf67e0f8d5f6180205ded11` |
| `typed_request_surface_sha256` | `cbdccf1679c6f534b501cf3f67b503c376fa6a155d0cf8f085306ad86c0a031c` | `cbdccf1679c6f534b501cf3f67b503c376fa6a155d0cf8f085306ad86c0a031c` |

No native or named-operation lane identity changed: 849 native rows and 153
named operation/version rows remain. The changed named public contract rows are:

- `object.setReference@2021.1`: `32e6c21571dd6efa17cad7b5efbc24c0ec24a219e96db156f6246a047f5e653e` → `4f13975b39f9bb92c3ac75313b819945a304a40fd310f387798d880a9978b633`.
- `object.createPlugin@2022.1`: `463d06569d9bbbf665200dbfbee3d662d201ba41fa310f94f19ad636a688dbf0` → `43570f9da7647b5a67d4e1c28a4c930951ae036d245d96787b82874a9c4bec15`.
- `object.setReference@2022.1`: `1b916552173937ef2b234b95be30e320733fcee1a95a3fd9a7d8c9d6396a80de` → `2685bfbe2ed7428a942337cb2a227641057a9f3f6f7884a8d9a8308d5d120eac`.
- `object.createPlugin@2023.1`: `eee5b29b1093be9fca5822370de9bd0cada746f78365148791dba88ab43ce055` → `53fffce82e2b8bc5c29e7b212049f61406f8fe418f775155bcd37d45a4ef3d08`.
- `object.setReference@2023.1`: `48eee4c941eb2f86c60a8ebbfe07a9ed5f972441296320f7435df820e4fab78e` → `ca73e8be418e6cc0fb640446922e1492e04ec1c66a9b10595c7b840bd34af20e`.
- `object.createPlugin@2024.1`: `7bc3940d45b9b55656ef6837af91c97902aee980c51586520300b611c839f273` → `8c844624e186ef3f8be656f974515100e89954d21a1d3c7822548867b440fe5e`.
- `object.setReference@2024.1`: `135d08ff8c1be057e838c141f4bf204b54a962c49077e88d6e4e36cdbef60c5b` → `c30f1516bdcb6838d850be9aa2d7d9b2d84cbe6ad7f85ba61e9c9a5c450bb5f3`.
- `object.createPlugin@2025.1`: `eef94b88aab61ce499464001c0c22e7a80f040b0bbdebabdd5b7f8a83eaa47e3` → `558b637a45360f4546dea51cf46349ef550b8914c436f960a4605a7f28b2a7e8`.
- `object.setReference@2025.1`: `5f0f096a7cc629af07fdb4286c2e3ca9a524a3967541576cee494bdafd6c6621` → `24d96cfc6484abd2b9b0774581814408abaa73dd151a093b072a67bfb289f4ae`.

The new metadata locator ownership is reviewed as Gateway derivation, while
its page-size scalar remains user-selectable. Group audit descriptions now name
placement, dependency and resource-lifecycle limits instead of granting all
business combinations inherited family credit.

Fixed/native field-contract hashes changed on 25 versioned rows, covering
`ak.wwise.core.object.getAttenuationCurve`, `ak.wwise.core.object.getPropertyAndReferenceNames`, `ak.wwise.core.object.getPropertyInfo`, `ak.wwise.core.object.getTypes`, `ak.wwise.core.object.isPropertyEnabled`.
The interned field-contract table has 196 records and the named argument-contract table has 35 records. These are structural counts, not functional passes.

Focused validation completed on this reconciliation: 27 passed in 245.71s
(`test_interface_depth_inventory.py` and `test_branch_coverage_audit.py`). Both
existing producers' `--check` commands returned 0. The branch audit remains
structurally consistent and behavior coverage remains incomplete; its CLI test
continues to require exit 2 from `--require-complete`. These maintainer checks
launch neither Wwise nor Fresh and add no functional execution credit.

## Portable source identities

Review follow-up `19ec7f53` centralizes repository source identities in
`tests/maintenance/source_identity.py`. Its relative POSIX spelling rejects
traversal and covers POSIX, Windows drive and UNC inputs without changing
native evidence provenance. The branch audit seals that helper as a source
dependency. These synthetic path tests do not establish native-Windows Wwise
execution. Final regeneration preserves the same runtime contract seals.

After the portability merge, 29 focused source-identity, depth-inventory and
profile-schema attribution checks passed in 58.51s. Both generator `--check`
commands again returned 0. Runtime seals and all structural counts above stayed
unchanged; the refreshed branch ledger adds the portable helper's source seal.

## Saved Source continuation parser review

At `c4c56351`, the parser projection adds only `continue-source-copy-proof`.
Removing that row reproduces the prior reviewed parser hash
`dce2f9c49744069a16be79a3e145bbdb0dfee2190d3d53e1e2836ebb343d46b0` exactly;
the complete projection hashes to
`26fc00e581429d36a11c09c9f66d51e21f24ae5e0968d7acc5a8e37dad998cb7`.
All prior command/parameter rows and the other three source-contract seals are
unchanged. The first integration generation stopped on this stale policy seal
before writing derived files or starting the evidence capture.

The command consumes the Gateway-issued owner identity and, for a checked parent
Draft, its issued task authority and revision. The disclosed `--decline-save`
choice records explicit refusal; it does not execute Save. Generated Save
children retain separate Preview and policy/confirmation authorization, durable
parent bindings, configuration checks and execute-once guards. Callers copy the
issued continuation; they do not construct a native request or choose another
project. This review admits the parser contract only. Complete saved-graph proof
remains restricted to the eligible 2021.1 Source shape; it grants no new native,
Fresh or exhaustive business-coverage credit.

## R92 cumulative integration reconciliation

Reviewed integration candidate: `66a0677f13a290c274d98b59ec35c93e9f4e7546`.
The prior reviewed policy at `c5b93c31` was reproduced exactly in a separate
immutable snapshot before comparison. Independent interpreter processes loaded
the producer functions and runtime only from their matching snapshot; import
roots were checked. The `927f4468` to `4bd56cf6` successor has zero changes in
all three canonical projections, and the merged candidate changes only the
test-inventory record relative to that successor. The cumulative seals are:

| Seal | Previous reviewed value | Reconciled value |
| --- | --- | --- |
| `gateway_parser_sha256` | `26fc00e581429d36a11c09c9f66d51e21f24ae5e0968d7acc5a8e37dad998cb7` | `6dc4cb03ba12b6a935006231270bc431187ba9367575efc15718fe645d0af3bb` |
| `operation_contract_sha256` | `3c8e8b29b141e084653af5dc682ae5b6e990b0d4a7ea49e6e84697a65f9c9be1` | `b2d76899195fbd342375b80651c80b8d5229af2330cd0ee8d991645d242b5b59` |
| `public_continuation_sha256` | `d70ab5cd8cb16538326e7939250429dd86ea03dc7993f3f110fa25438f05e5c0` | `7e63798666897561b08432f6016228adb55199bd4a47f15d48314ea1bcaf5584` |
| `typed_request_surface_sha256` | `829f71b2cca1e2779e14f7c681cc3802b94945f9a9a9e111c070c82478151150` | `829f71b2cca1e2779e14f7c681cc3802b94945f9a9a9e111c070c82478151150` |

The typed-request surface is byte-identical. Named operation/version identities
remain 153, with 23 changed public contract rows: `object.set` and
`object.setRTPC` on 2022.1–2025.1, and `object.setProperty`,
`object.setReference` and `waapi.undoGroup` on all five versions. Their changes
are the reviewed owned Modulator/Time alternatives and boundaries; Switch-child
structural identity and receipt-bound history; source-bound master-Bus reference
applicability; finite named Metadata and anonymous Marker construction; and
actual-native-name staged creation/history. Scalar field semantics, exact
identity and preservation proofs remain Gateway-owned. Typed List restoration,
old-custom replacement disposition, mixed-platform inputs and broader
conflict/history combinations remain unfinished under their existing owners.

The declared continuation projection retains 897 identities and changes 114
rows. Eighty-two existing core-call rows inherit the shared meter parser flags;
26 existing metadata rows inherit versioned curve-role validation rather than
a fixed seven-choice argparse list. These shared-parser repetitions do not add
routes. Five object.get rows disclose closed local-reference and override-source
values, related singleton/list/sequence/reducer outputs, metadata-bound scalar
and reference conditions, safe namespaced scalar conditions, randomizers,
finite local Lists and source-certified reference kinds. Blend Track output is
only 2024.1/2025.1. Read projections retain identity, occurrence, metadata,
result and page bounds and never confer mutation authority. The remaining row
is the reviewed 2025.1 structureChanged public Notes match compatibility:
derived digest/handles change while raw catalogs and native branch IDs stay
fixed. Filtered delivery and Authoring effects remain separate acceptance work.

The parser grows from 78 to 79 rows. The only added command is
`draft-bind-switch-child-context`, accepting copied Draft/task/revision/owner/
child authority. Seven existing rows change: core-call gains eleven closed
meter output/scope flags; draft-declare-field-change and draft-declare-rtpc gain
four new-owned-ControlInput flags, with existing input now an exclusive
alternative; query-object gains local/override/related/condition options;
metadata defers curve-role validation to matching-version preflight; and the
query-schema output and source-control usage-output choices inherit
blend-tracks. All prior root parser fields are unchanged.

These changes reuse the reviewed components and exact evidence scopes recorded
in `tests/TEST_INVENTORY.md`: R59 owned construction, R67–R69 output modes,
R71–R76 related queries and structural identity/history, R77–R83 staged graphs
and metadata-bound conditions, R84–R90 finite Metadata/Marker/List/randomizer
contracts, and R90–R92 scoped Profiler/control repairs. Original failed and
indeterminate receipts keep their original candidates and verdicts; component
checks are not added together or promoted to whole-ticket acceptance.

### Dynamic public-schema boundary

Zero successor projection delta does not mean unchanged runtime public
verification descriptions. The producer copies non-named declarations from
the packaged typed-request surface; it does not dynamically re-evaluate every
exact-URI request-schema contract. F3 and F6 are reviewed through their direct
public-schema and transaction controls, separately from these source seals:

- Transport executeAction, all five versions, adds closed action-meaning and
  bounded verification disclosures: selected/all-active association checks,
  toggle prestate, at most 64 targets and one later getState observation per
  target. Transient playback and unresolved native action semantics remain
  unverified. No continuous, causal or atomic-snapshot guarantee is made.
- Profiler saveCapture, 2023.1–2025.1, adds exact authorized nonempty created or
  content-changed artifact proof and bounded regular-file preservation. Native
  capture format validity and content completeness remain unverified.

The reviewed F6 repair at `0aeaee85` rejects redirected root/destination identity
before content reads; the reviewed F3 repair at `4bd56cf6` rejects retired or
replaced selected-handle generations and preserves deferred verification on
unavailable membership reads. Neither changes accepted input fields, parser or
version scope. Their independent reviews resolved the causal findings; the
existing receipts and native-effect limits stay explicit. This reconciliation
adds no generic inventory architecture and no native/Fresh execution credit.

The final audit must retain this precise projection limit. Regeneration is
source-consistency accounting, not promotion of pending source-only mappings,
including the historical f72 proposal. Existing IDs, owners, dispositions,
requirements and evidence provenance are preserved.

### R92 generation result and retained Source bridge blocker

The existing interface-depth producer and its `--check` both returned 0 on the
owned reconciliation worktree based at `66a0677f`. Its summary, dispositions,
owners, native and operation identities, family assignments and mechanic states
are unchanged. Only five object.get field-contract digests and 23 named contract
digests change; nine named rows also change their argument-contract digest. The
interned tables remain 217 field contracts and 35 argument contracts.

The subsequent existing branch producer returned 1 before writing any artifact:
`Original Source proof/context/public configuration differs`. Its sealed Source
native attachment contexts disagree with current dependency hashes on the same
32 files for all five versions. Eight of those files already differed at the
previous reviewed policy base; none is the policy or regenerated depth file.
This is a retained evidence-source dependency review, not a new native execution
failure. The original attachments, branch artifacts and evidence index were not
modified or re-sealed. Branch `--check` and completion checks remain unrun until
that explicit bridge reconciliation is accepted; no complete branch generation
or current branch-coverage consistency is claimed by this partial result.


## #195 derived surface reconciliation — 2026-10-29

Reviewed runtime integration base: `4bc5952bc1830ccc183d54082f15d896d47cf06a`.
This is derived publication only: no public runtime contract, reflected native
schema, route identity, ownership rule, completion disposition or functional
receipt is changed. The prior review history above remains unchanged.

The preceding policy's four exact projections were reproduced in a separate
immutable worktree/interpreter at `e557cea9ce5d60f78821fd7b13d14121f6937536`.
Both comparisons load the matching repository's existing parser, operation and
continuation producers. Current typed data is produced by
`build_typed_request_surface` with `DeterministicJsonWriter`, using all five
pinned definition graphs and the existing Authoring supplements. There are no
added/removed rows, native schema/definition digests, execution-policy changes,
construction-shape changes, unresolved references or unknown schema keywords.
The native maximum-profile surface remains 897 lanes: 737 functions/160 Topics,
193/35 unique URIs; named operations retain 153 versioned identities.

### Exact public projection deltas

- Typed surface: 21 existing 2024.1/2025.1 UI business-contract rows change;
  every other lane field and the native result-definition graphs stay exact.
  Two `setLayout` rows disclose the existing closed blueprint constructor's
  ObjectPanel/ObjectTabPanel, floating windows, position history, optional root,
  explicit type inclusion and typed bounded ViewData entries. Gateway-derived
  IDs/native tags, 128-item bounds, depth/byte ceilings and known splitter,
  sidebar, holder/allOf and read-vs-request limits remain explicit. No retained
  schema is rewritten and no native setLayout input acceptance is inferred.
  The 2025.1 reset selection text labels its 32-entry cap as Gateway capacity,
  preserving omission/empty/ordered selection distinctions and the unproved
  default-state oracle. Eighteen owned model/window/signal rows change only
  `native_effect_evidence` from `required_unfinished` to
  `not_independently_verified`; visible window effects and signal delivery are
  still not proved by a result. These existing source/code disclosures follow
  the 2026-10-27 lightweight policy in the full-coverage SPEC; they do not change
  #188/#189 ownership, unfinished interface dispositions or native credit.
- Parser: 79 command rows remain; 11 change. `core-call` adds nine existing
  semantic projection/language/platform flags. `draft-add-media` adds explicit
  source-control choices; `draft-bind-object` adds the issued created-result
  handle; `draft-declare-core-plan` adds closed type/empty declarations. Existing
  import declaration/revision commands add the six bound DialogueEvent/condition
  flags. SoundBank declarations add explicit all/empty/language/temporary/disk
  choices and their source alternative. Existing query and source-control output
  choices gain declared finite outputs. No root flag or command identity changes;
  native envelopes, property paths, lookup identities and execution mechanics
  remain Gateway-owned.
- Named public contracts: 45 rows change across ten existing operations:
  `audio.import` (5), `object.create` (5), `object.createPlugin` (4),
  `object.set` (4), `object.setName` (5), `object.setRTPC` (4),
  `soundbank.convertExternalSources` (4), `soundbank.generate` (5),
  `soundbank.processDefinitionFiles` (4), and `waapi.undoGroup` (5).
  These record the existing bound Source/Switch/DialogueEvent import choices;
  source-certified Action, Query, WorkUnit and ControlSurface creation/name
  boundaries; version-correct owned Metadata placement and anonymous List/music/
  MediaPool construction; explicit mixed-platform ControlInput replacement and
  preservation; optional external-source destination; all/empty SoundBank
  generation and Definition identity forms; and source List admission separated
  from optional history restoration observers. Closed declarations, exact user
  artifacts, scoped handles, Preview/authorization/execute-once and truthful
  weaker-verification modes remain in force. None becomes raw native args/options
  or model-authored mutation WAQL, and no named operation identity is added.
- Continuations: 897 identities remain; 108 rows change. Eighty-two repeat the
  existing shared core-call parser additions only. Five object.get rows also
  update their fixed parser and current closed business/advanced query layers.
  Twenty-one carry the UI declaration changes above. Fixed reflected native
  inputs are not promoted to public model-authored payloads.

The uniform deep-interface invariant and all ownership/migration/completed-family
rules are unchanged. Existing layout/model rows remain assigned to #188/#189;
this source reconciliation neither closes those obligations nor transfers any
historical Program/native/Fresh PASS. The previously documented continuation
projection limit still applies: it is not a claim that every dynamically
returned verification description was re-executed.

| Seal | Previous reviewed value | Reconciled value |
| --- | --- | --- |
| `gateway_parser_sha256` | `73309b23de133e29fea37cdd7fb15eccc913cc3f0d5eff6fd98f92143184c5f9` | `5a640976764f6ba0684217143c4470a5048a5a0c4ab012a39d024dfd9b51abd9` |
| `operation_contract_sha256` | `b2d76899195fbd342375b80651c80b8d5229af2330cd0ee8d991645d242b5b59` | `cf67ed6bf215060cdb1aec78c5c7ca0137d520cbd00c1f52fa3f87a5400d8137` |
| `public_continuation_sha256` | `74461fb6908cb5e2f66b89765cf07db12a6887895d06966883d93672c20f827b` | `dea44f6f11c71e91c4c917f21980437b6b8afdefa22fd3bd3b912fe1bb00b82e` |
| `typed_request_surface_sha256` | `829f71b2cca1e2779e14f7c681cc3802b94945f9a9a9e111c070c82478151150` | `36bb15ba469c614c5428ef847214d1466d2b6ee49d012bd405936bc52a997edc` |

Generation and focused validation results for this reconciliation are recorded
below only after the corresponding commands actually finish. Canonical branch
coverage index/requirements, Source/native/applicability proofs, class-replay
bridges and current CODE receipts are outside this publication slice.


### #195 completed generation and focused validation

The existing full-surface release writer and its `--check`, and the existing
interface-depth generator and its `--check`, all returned 0. The release report
changes only its typed `source_inventory` digest; all eight audit lists remain
empty and construction counts are unchanged. The depth summary, all 897 native
rows, all ownership/disposition/completed-family rules and all 218 interned
field-contract records are unchanged. The 35-record named argument table
replaces two records and retains 33 exact hashes; 45 existing operation rows
update contract and/or argument-contract digests. No expected count was edited.

On committed source `6bbe0448f194fb60a919afa084315adc0e23e487`, the exact nine
previously failing typed/release/depth cases plus seven existing definition,
reference/keyword, ownership, unfinished-layout and closed-child guards passed:
**16 passed in 61.37 seconds**, exit 0. The two representative pre-publication
controls had failed in 0.97 seconds with the original typed-surface/parser-seal
errors. These focused checks used the locked Poetry interpreter through
`ci/test.sh --mode nonlive` with exact node selection; they started neither
Wwise nor Fresh. No full Program/Non-live gate, branch-coverage generation,
canonical evidence import/evaluation, proof refresh or functional credit
transfer is claimed. Current source admission and the original failed gates
remain separate work under #195.


## #195 UI wrapper migration reconciliation — 2026-10-29

The accepted lightweight policy in `SPEC.md` (2026-10-27), the
[#188 close](https://github.com/zcyh147/waapi-skill/issues/188#issuecomment-6433636019)
and [#189 close](https://github.com/zcyh147/waapi-skill/issues/189#issuecomment-6434676769)
accept functional wrapper completion. The
[no-further-native reaffirmation](https://github.com/zcyh147/waapi-skill/issues/189#issuecomment-6436636116)
retains the window failures and consumed startup BLOCKED attempt. The previous
`authoring-*-partial` policy rationales incorrectly treated the retained native
uncertainties as unfinished caller-interface migration. Their stable family IDs
`authoring-layout-partial` and `authoring-model-partial` are retained for branch
producer compatibility; each now has its own exact completed-family seal. The
legacy ID spelling is not the current disposition. The eight historical seals
remain unchanged.
The completed ticket blueprints/issue rollups are removed through the existing
policy mechanism. No native input/effect/delivery or cleanup proof is added.

The review compared all 48 exact current rows against the accepted closeout
candidate `7e4def957f9246c8f1ab7fa46c8e655df41a8022`, which includes layout closeout
`c5ba64e56d66632a6987913c934d1e729128f954`. Separate interpreter processes loaded
each worktree's existing `build_typed_request_surface`,
`_public_continuation_rows` and `_typed_field_rows`. Every complete lane record,
actual public continuation/parser projection and field-ownership projection
matched, not merely counts or empty leak arrays. Both 48-record canonical
SHA-256 values are
`b54835e2392e127eb3eff706faf714d465f5e486fc4be298df97a75d41b7c2e0`.
The dedicated layout read/handle/business, model business and WAFM/blueprint
constructor modules and their pinned native supplements/catalogs were inspected
against the accepted mappings; no new ordinary input or route gap was found.
The highest seams remain the following exact closed business contracts.

| Exact URI suffix after `ak.wwise.ui.` | Versions | Highest public seam and caller values |
| --- | --- | --- |
| `layout.closeView` | 2025.1 | `draft-declare-layout-plan`; `layout_handle`, `view_handle` |
| `layout.dockView` | 2024.1, 2025.1 | `draft-declare-layout-plan`; `layout_handle`, `view_handle`, `target_element_handle`, `dock_side` |
| `layout.getCurrentLayoutName` | 2024.1, 2025.1 | `layout-read current`; no caller values |
| `layout.getElementRectangle` | 2024.1, 2025.1 | `layout-read rectangle`; `element_handle` |
| `layout.getLayout` | 2024.1, 2025.1 | `layout-read contents`; `layout_name` |
| `layout.getLayoutNames` | 2024.1, 2025.1 | `layout-read names`; no caller values |
| `layout.getOrCreateView` | 2024.1, 2025.1 | `draft-declare-layout-plan`; `layout_handle`, `view_type`, `initial_x`, `initial_y` |
| `layout.getViewHandle` | 2024.1, 2025.1 | `layout-read frontend`; `view_handle` |
| `layout.getViewInstances` | 2024.1, 2025.1 | `layout-read instances`; `layout_name` |
| `layout.getViewTypes` | 2024.1, 2025.1 | `layout-read types`; no caller values |
| `layout.moveSplitter` | 2024.1, 2025.1 | `draft-declare-layout-plan`; `layout_handle`, `splitter_handle`, `pixel_delta` |
| `layout.removeLayout` | 2024.1, 2025.1 | `draft-declare-layout-plan`; `layout_handle` |
| `layout.resetLayouts` | 2025.1 | `draft-declare-layout-plan`; `layout_handle`, `reset_scope`, `reset_layout_handles` |
| `layout.setLayout` | 2024.1, 2025.1 | `draft-declare-layout-plan`; `layout_handle`, `new_layout_name`, `blueprint` |
| `layout.switchLayout` | 2024.1, 2025.1 | `draft-declare-layout-plan`; `layout_handle` |
| `layout.undockView` | 2024.1, 2025.1 | `draft-declare-layout-plan`; `layout_handle`, `view_handle`, `position_x`, `position_y` |
| `model.createHandle` | 2024.1, 2025.1 | `draft-declare-model-plan`; `window`, `template`, `template_key` |
| `model.destroyHandle` | 2024.1, 2025.1 | `draft-declare-model-plan`; `model` |
| `model.getState` | 2024.1, 2025.1 | `draft-declare-model-plan`; `model`, `widgets` |
| `model.registerWafm` | 2024.1, 2025.1 | `draft-declare-model-plan`; `template_key`, `root_widget`, `widgets`, `layouts`, `registration_medium`, `registration_form`, `template_version`, `metadata`, `templates` |
| `model.setState` | 2024.1, 2025.1 | `draft-declare-model-plan`; `model`, `widgets` |
| `signal.emit` | 2024.1, 2025.1 | `draft-declare-model-plan`; `model`, `widget`, `signal` |
| `window.close` | 2024.1, 2025.1 | `draft-declare-model-plan`; `window` |
| `window.create` | 2024.1, 2025.1 | `draft-declare-model-plan`; `title`, `width`, `height` |
| `window.present` | 2024.1, 2025.1 | `draft-declare-model-plan`; `window` |

Layout reads construct native names/IDs inside the Gateway; rectangle/frontend
reads require issued layout/view handles. Mutations derive native envelopes,
constructor IDs, native docking topology and splitter axis from scoped live
identities. The actual contracts retain automatic Authoring-host/version checks,
configuration/session/project binding, all modification policies, immutable
Preview, drift revalidation, execute-once, non-retry and bounded state readbacks.
The pinned 2021.1–2023.1 Authoring catalogs omit these exact layout routes.
`LAYOUT_CONSTRUCTION.md` records the accepted 30-row mapping, closed named
constructors, optional/empty/repeated forms and Gateway capacity limits. The
unsatisfiable Splitter request definition, capital OneOf/sidebar/ViewHolder
questions and read-only extra fields remain explicit source boundaries, not
invented setter grammar or native absence. Preferred-height/sidebar/frontend,
arrangement and reset uncertainty remain; reset still has schema-only strength
and `business_state_verified=false`. Representative controls remain in
`test_authoring_layout_{gateway,mutation_gateway,blueprint_gateway,splitter_gateway}.py`:
closed reads/non-bypass, scoped drift, all policies, exact nested construction,
raw-map rejection, one write and requested-state comparison. These unchanged
runtime controls are retained evidence, not a new native run.

Model/window/signal plans use bounded typed construction and copied opaque
resources, never native GUIDs, XML, payloads or executable content. The actual
contracts bind configuration/host/build/session/project and active parents,
freeze generated-file proofs, keep separately previewed close/destroy, reject
stale ownership and missing creation identities, and do not retry unknown
creation outcomes. All 18 disclose `native_effect_evidence=not_independently_verified`
before authorization. State assignment readback remains independent; other
results retain schema-only strength and `business_state_verified=false`.
Emission is not delivery, and consumed cleanup authority is not independent
native closure proof. Templates retire at session end without an invented
unregister route. Earlier exact-route/build absence is not universal business
absence. `AUTHORING_MODEL_TOPIC_CLOSEOUT.md` and existing model Gateway controls
retain the accepted source interpretation, ownership, file drift, rejected
registration, pending-model cleanup ordering and original native FAIL/BLOCKED
history. No native or Fresh test is authorized by this reconciliation.

The completed seals bind exactly 30 layout identities
(`ce35bc537d44419f735e74285ed52659c3483e1037dde5d085013e198be98c28`)
and 18 model/window/signal identities
(`e8e9e05a471620cedbc3f55c6d77fc082e5b9f1a7411b87ebb27c9ceaf46ca88`).
Native row identities, field/argument contracts, all four source-contract seals,
operation rows, uniform-depth rules and raw escape prohibitions remain unchanged.
Completion here means accepted bounded functional wrapper depth only; native
PASS/support and final #195 gate acceptance are separate claims.
