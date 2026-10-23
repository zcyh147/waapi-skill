# Test inventory

This inventory is grouped for human review. The dated entries below distinguish
complete runs from focused follow-ups; broad coverage is summarized by file or
module instead of listing every item instance. Program and Non-live results
are not live-Wwise or Fresh Agent evidence.

## 2026-10-23 R84 related property outputs and existing EQ witness

Reviewed `6e0aa118` extends existing related scalar-property terminals to fresh
metadata-selected namespaced fields, in both ordinary and override-source-value
modes. Singleton, list, selected sequence and combined outputs use their existing
planners; reference hops and reference terminals retain their previous kind and
token boundaries. Root output behavior and general expression grammar are
unchanged. The final five-version affected selection passed 227 checks in
12.24s; earlier failed assertions and repairs remain in the original logs.
Test-only output controls passed five checks in 1.33s before native execution.

Frozen `a5439459` passed one matching macOS Console2025.1.7.9143 workflow in
6.78s: seven public read groups, seven invocations, 30 hashed native packets and
zero transactions. Root, AudioFileSource-to-parent and selected child-list
outputs returned actual typed integer-zero values for both @MyCompany:Status
and @@MyCompany:Status. Fresh scoped metadata, actual parent identity/class,
complete selected membership and repeated root values matched the public output.
Source hash/mtime/tree and lifecycle cleanup passed. Evidence:
`r84-namespaced-outputs-a5439459-2025-r1/root-review.json`. This establishes the
selected 2025 native outputs, not an inheritance difference or five-version
native execution. Earlier R82/R83 condition witnesses were not repeated.

The separate existing-EQ test on the same candidate failed in 4.14s before any
Draft or write. Its collector incorrectly required the query-only terminal
`agent_result` field on the successful `status` response, which has no such
field. One public status invocation and two hashed read-only native packets were
captured; no transaction occurred. Source integrity and process cleanup passed;
the failed sandbox remains quarantined. The original FAIL is retained at
`r84-eq-gain-a5439459-2025-r1/root-review.json`. This is a test-oracle mismatch,
not evidence of an EQ implementation failure or a passing EQ business outcome.
The test-only repair `477b0049` added a complete public Gateway/fake-transport
collector flow, which also caught a nine-field request exceeding the existing
eight-field ceiling. The corrected 8+1 queries compare identity envelopes;
`66a2a1f1` preserves each original response before joining the separate context.
The affected controls passed 25 in 2.14s, followed by four full-flow controls in
2.12s after Main's exact-response preservation finding. These runs overlap.

Frozen `66a2a1f1` then passed the selected existing-EQ native workflow on macOS
Console2025.1.7.9143 in 7.04s. One verified transaction changed Voice_EQ GainBand1
from 4 to 3; 19 independent reads and 114 hashed native packets establish the
actual Effect class6881283, all three Gain dependency clauses and recursive
controller metadata. NumBands3, OnOffBand1true, FilterTypeBand1=4, other observed
target values, peer values, complete ordered folder membership and selected
metadata remained unchanged. The platform came from actual project status.
No setup/history transaction occurred; source integrity and cleanup passed.
Evidence: `r84-eq-gain-66a2a1f1-2025-r2/root-review.json`. The original failed
root remains unchanged. This is one actual existing-EQ composition witness,
not every plugin, band, version or audio-state verification. Neither slice adds
Fresh or full-gate evidence.

## 2026-10-23 R82 duplicate creation and namespaced query witness

Reviewed SET implementation `878cde58`, integrated at `79f76858`, gives duplicate
ordinary rename declarations distinct result handles. It creates an ambiguous
sibling group in declaration order against the actual owned parent GUID, retains
each native result separately, and checks the cumulative created roster before
later writes. Public results and owned history retain every observed occurrence;
actual names are verified exactly without guessing Wwise suffixes.

The public source/verify/undo/redo tracer passed in 27.96s; the public complete
roster assertion initially failed, then passed in 28.24s. Focused shape and causal
controls retained their initial failures: the suffix-like name repair passed in
5.24s, and a corrected between-stage test hook passed in 4.03s. Final affected
existing callers passed nine checks in 25.33s. Original logs and two independent
reviews are retained in `r82-reviewed-evidence`; overlapping runs are not summed.
Reviews found no material issue. Those initial checks were program evidence.
The reviewed test-only successor `993a8e1a` then passed the matching macOS
Console2025.1.7.9143 SET duplicate workflow in 23.86s: three separately verified
source/undo/redo transactions, 19 independent observations, 60 public commands
and 232 hashed native packets. Wwise returned distinct Send and Send_01 objects
under the newly created parent's actual GUID; reference and public occurrence
roster matched independent reads. Undo restored the baseline and proved all
three new GUIDs absent; redo restored the exact original created graph and
reference. Source integrity and cleanup passed. Exact stage results and three
missing-GUID errors were matched to their original native packets. Root:
`r82-duplicate-set-993a8e1a-2025-r1/root-review.json`. This is selected 2025 SET
composition evidence, not a CREATE or all-version duplicate native result.

Reviewed CREATE successor `c9dadc2b` extends that owned-stage mechanism across
2021–2025: later creates use the actual parent GUID and each deferred reference
uses closed setReference. Shared history observations consume the complete
actual roster; compound phases avoid the old requested-path rewrite. The 2021
public source workflow passed in 1.21s; 2025 compound source/undo/redo passed in
24.46s. Three middle-version source/count cases and four causal stops passed
seven checks in 5.64s; final existing CREATE/SET callers passed seven in 15.70s.
Counts overlap. Original failures and fixes are retained in
`r83-create-reviewed-evidence`; Main's runtime and final-delta review found no
material issue. The test-only successor `e51f4ff8` then passed on matching
macOS Console2021.1.14.8108 in 10.38s: one verified transaction, zero setup or
history transactions, nine independent reads, 27 public commands and 117 hashed
native packets. Three CREATE calls used actual parent GUIDs, then one closed
setReference connected the correct actual siblings. Full public occurrence
roster, original owner/ancestor/leaves, matching 2021 field metadata and source
integrity/cleanup passed. All four stage results match their original native
packets. Root: `r83-duplicate-create-e51f4ff8-2021-r1/root-review.json`.

The accepted component assessment
`r83-duplicate-creation-component-acceptance.json` combines that CREATE witness,
new 2025 SET duplicate/history evidence, retained matching 2025 ordinary CREATE
history and current five-version program/CREATE history-adapter checks. It
justifies shared-mechanism reuse without an additional 2025 CREATE history
chain, while explicitly not claiming a directly observed 2025 staged-CREATE
native run or every-version native matrix. Broader conflict policies, graph
shapes and constructor/history alternatives remain assigned to #178/#192.

Test-only candidate `1c5a07b7` passed one macOS Console2025.1.7.9143 namespaced
query witness in 9.71s. The private project copy loaded the official
`MyCompany:Status` custom property; fresh actual Sound metadata disclosed its
integer default zero and enumeration. Seven public query groups and nine hashed
native packets showed both ordinary and override-source-value WHERE predicates
select the Sound for zero and no object for one. The fixture made zero
transactions; original project/work-unit data, source hash/mtime/tree and cleanup
passed. Root `r82-namespaced-query-1c5a07b7-2025-r1` retains final-v3 evidence,
exact packets and Main review. Thirteen fixture program checks passed in 0.51s
before the native run. This proves matching-2025 token/membership acceptance,
not custom-value RETURN, an inheritance difference, or five-version native
coverage. Reviewed implementation `778df7fa`, integrated at `633731c0`, now
admits fresh metadata-selected namespaced scalar properties in ordinary and
override-source-value business conditions. Token permission is applied on every
binding after actual-object kind fallback; cached discovery cannot grant the
condition's permission to outputs or reference hops. Generic accessor grammar
and mandatory typed predicate-value RETURN/readback checks are unchanged.

The final five-version focused file passed 96 checks in 7.21s. The existing
scalar/reference/related selection passed 170 in 18.25s; after its last fallback
repair, 50 directly affected checks passed in 2.08s. These counts overlap.
Initial field-token, disclosure and exact-object fallback failures remain
preserved in `r83-namespaced-reviewed-evidence`. Independent review found no
material issue and checked all five definitions and embedded source hashes.
The separate closed-business witness passed at frozen `b3aedf70` on macOS
Console2025.1.7.9143 in 8.73s: seven public query groups, 33 hashed native packets
and zero transactions. Actual typed @MyCompany:Status and @@MyCompany:Status
values were zero in all eight before/after observations; all four positive and
negative native selections matched public IDs, with fresh class metadata,
complete source scopes and unchanged source/cleanup. Root:
`r83-namespaced-business-b3aedf70-2025-r1/root-review.json`. This completes the
selected public-flow readback acceptance; it is separate from the earlier
advanced identity-only witness. Equal local/resolved values do not prove an
inheritance difference or all-version native coverage. A subsequent one-string
schema disclosure cleanup `dbcb1eb3` preserves the mandatory live readback rule;
five existing schema/source checks passed in 0.35s, without a native rerun.
No Fresh or full gate ran for this slice.

## 2026-10-23 R81 reference and override query conditions

Reviewed implementation `6316028a`, integrated at `39052582`, adds metadata-bound
`reference`, `local-reference` and `override-source-value` predicates to the
shared root/related query mechanism. Five pinned WHERE source sections support
the owned identity, null/setness, negation and override expressions separately
from RETURN projection evidence. Canonical GUID comparison constants require
no target-existence read; named selectors use bounded unique resolution and
revalidation. Native predicates determine results, including inequality with
unset references. The public interface does not accept arbitrary accessors.

Original failures and their narrow repairs are retained. Initial unsupported
modes failed 11 checks. Runtime expansion passed 75 while five schema assertions
failed, then those five passed after disclosure was added. A later selection
passed 80 and exposed five named-selector drift failures; those five passed
after revalidation was repaired. Additional mode/type controls passed 50.
The final affected selections passed 122 in 16.24s and 60 in 16.06s, including
existing scalar consumers, source completeness, typed pages and reducers. Counts
overlap and do not represent a full-file or full-gate total. Independent static
review found no material issue; originals, source notes and review are archived
in `r81-reference-condition-program-logs`.

The reviewed test-only successor `f28e51c2`, integrated at frozen
`eb02a2390a4c4d87ee5dd37f1280322c83f578eb`, passed on macOS Console2025.1.7.9143
in5.88s: eight compact public query groups, eight invocations,82 hashed native
packets and zero transactions. Independent unfiltered source/value observations
and actual native WHERE membership prove resolved/local references, known-set
null/setness/inequality and ordinary versus override scalar values. Fresh local
UserAuxSend0 returned a present zero-GUID reference with matching native metadata;
its null predicate selected the Sound, while setness and identity inequality
selected no rows. The implementation preserves that native inequality outcome,
not a Python complement. Source hash/mtime/tree and cleanup passed. Evidence root
`r81-reference-query-eb02a239-2025-r1` includes the original final-v3 record and
Root review. Existing all-five projection/program evidence remains separately
attributed.

The reduced oldest-backend successor `e3abcbfa165906dda6b7ac3812b83d078a422c1c`
passed macOS Console2021.1.14.8108 in9.25s. One lifecycle covered four core groups
plus three separately observed unassigned-reference predicates: seven public
queries,73 hashed native packets and zero transactions. Matching2021 observations
establish a present zero-GUID UserAuxSend0 value, null selecting the Sound, and
setness/identity inequality selecting no rows; these facts were observed afresh,
not inferred from2025. Source/cleanup passed. The original2025 native run was not
repeated for this test-only variant. Aggregate evidence is
`r81-reference-query-native-review-2021-2025.json`; exact roots retain original
candidates and final-v3 records. Five-version primary semantics/program controls
and earlier matching-host projection/ordinary-condition evidence support shared
mechanism reuse; no intermediate-version native matrix was added.

No Fresh or full gate ran. Collision-specific and exact namespaced custom-property
WHERE token facts remain #181 work; the disclosed current token boundary is not
native absence. Other query records, reference chains, functions and legacy
alternatives remain assigned to the same ticket. These are selected2021/2025 predicate
observations, not every-version native query coverage.

## 2026-10-23 R80 owned Action history and multiple-root creation

Action history implementation `274119a3`, integrated at `62e4bac0`, retains the
actual before/after Action identity, class, parent and typed ActionType in the
source verifier's original read. Owned undo/redo consumes that witness and
revalidates native metadata and source-kind authority. It does not reconstruct
paths or enrich old executed receipts. Ordinary history and creation observers
remain on their existing contracts.

The initial public failure passed after repair. The expanded selection retained
46 passes and two native-typed metadata-extension failures; the two failures and
two valid counterparts then passed (4 in 4.20s). A parent-extension failure was
repaired and its four affected controls passed in 4.16s. Existing source/history
callers passed 58 in 24.89s. A malformed-witness diagnostic failure was repaired;
eight legacy/forged-receipt controls and a valid flow passed in 4.67s. The selections
overlap; original failures and repair attribution are retained in
`r80-action-history-program-logs`. Independent Root review found no actionable
issue in this slice.

Frozen `62e4bac0468d45bec124c9cd0715ea6639f711df` passed the macOS Console
2025.1.7.9143 Action retarget/undo/redo workflow in 14.35s. Three separately
authorized transactions verified; 30 independent queries and 163 hash-checked
native packets establish actual Target/path/controller changes and restoration,
Event children, peer Action and old/new audio-target preservation. Final v3
lifecycle evidence proves unchanged source hash/mtime/tree and completed process
and passing-sandbox cleanup. Evidence root:
`r80-action-history-62e4bac0-2025-r1`, including `root-review.json`.

This adds native owned-history evidence for the exercised 2025 Action flow.
Program controls cover 2022 undo and 2023–2025 undo/redo, both source-certified
and native-typed metadata, and the 2021 history/2022 redo catalog boundaries.
No other-version native history, global stack-head, outside-scope, full Action
family, Fresh or Windows acceptance follows. Matching five-version definitions
and public controls, retained R79 source effects, R76 matching-host history effects
and the new 2025 integration support proportional shared-mechanism reuse; the
review is `research/waapi-r80-action-history-version-reuse.md`. No additional
per-version run was selected without a differing branch. Other #192 obligations
stay open.

Separately, creation implementation `27d0abe8` and repair `ba8af705`, integrated
at `aec44f31`, stage ambiguous retained-parent roots individually and preserve
actual native GUIDs/names and separate results. The cumulative created roster is
reobserved before dependent reference writes. Independent review exposed an extra
child inserted under an earlier root; its failing public counterexample passed
after repair. Final affected controls passed 8 in 51.13s, including retained-read
replay, source/history and prior identity/collision guards. Earlier applicable
version/history controls remain separate overlapping evidence. Original logs,
review and repair are archived in `r80-multiple-root-program-logs`.

The prepared native fixture first failed in 6.08s before any transaction because
its observation directory did not yet exist (`35c6760f`). A test-only initialization
repair then reached verified creation/reference and undo, but failed in 15.53s
because an exact query for a deleted GUID returns a structured native Object not
found error, not an empty list (`ace89c4f`). Both original FAIL roots/quarantines
remain unchanged. The absence oracle now accepts only the exact owned GUID/query,
endpoint/version and native error; eight mismatched controls were rejected using
the retained real response. No Gateway behavior changed for these fixture repairs.

Frozen `cfd0d19a79a6883626d32c1eba83c70e3e05e70e` passed the complete macOS Console
2025.1.7.9143 workflow in 22.06s: zero setup transactions, three separately
verified source/undo/redo transactions, 20 independent observations, 62 public
commands and 285 hashed native packets. Separate native collision roots preserve
actual GUID/name binding; cumulative membership is checked before the internal
reference write. Undo restores the original scope and proves all four new GUIDs
absent; redo restores the same graph, names and reference. Source hash/mtime/tree
and final lifecycle cleanup passed. Evidence and Root review are in
`r81-multiple-root-cfd0d19a-2025-r3`; the two failed roots remain alongside it.
This proves the exercised 2025 ordinary two-root graph, not duplicate requested
siblings, richer creation/history forms or other-version native effects. Those
remain #178/#192 work. Neither increment ran a full Program or Non-live gate.

## 2026-10-23 R79 source-backed Action.Target kind

Reviewed implementation `c667a640`, integrated at `35d1ae1e`, supports the existing
Action.Target field when native metadata omits its kind. Matching SDK definitions
certify Reference separately; actual Action GUID, class, ActionType and raw
metadata remain bound through Field discovery, Preview, prewrite and verification.
Native restrictions are unchanged. No global empty-kind allowance or Sound-only
target restriction was added, and ordinary Show metadata remains visibility only.

The first public counterexample failed before repair, then passed. Expanded
controls passed 32 in 7.55s. The affected selection passed 110 with five new
fixture assertion failures in 25.44s; only those five corrected Preview-notice
checks reran and passed in 1.88s. Final eligibility/builder controls passed 13 in
2.31s. These selections overlap. Original logs and their causal reconciliation
are hash-archived in `r79-action-program-logs`; independent review found no
remaining actionable issue in the selected diff.

Frozen `35d1ae1e6c392a8bce0f13c436699270c39c845d` passed the existing Play Action
retarget workflow on macOS Console 2025.1 in 9.84s and 2021.1 in 9.39s. Both
actual object-scoped Target responses had empty native type/restriction, so the
separate documented-kind proof was exercised. Each case has one verified
transaction and 20 independent before/after queries; 2025 captured 85 native
packets and 2021 captured 81. Raw metadata hashes match the original packets.
The selected Action retains its GUID, intrinsic name, ActionType and other
observed fields while its display path follows the new target. Event membership,
peer Action/Event, old/new audio objects and sibling context are preserved.
Source integrity and cleanup passed; the lifecycle removed the passing sandboxes.

Evidence: `r79-action-target-native-review-2021-2025.json` and the two original
root reviews. All five versions retain source/program checks; native 2022–2024
was not repeated. No audio playback, complete Action-family, owned-history,
Fresh or Windows native acceptance is claimed. Source-kind history support stays
required work under #192; other #177/#178/#180 branches remain open. No full
Program or Non-live gate was added for this increment.

## 2026-10-23 R77 scalar conditions and R78 creation integration

Integration `2589b9a17d9f41b7f903af7a71c34917488b9a94` combines the reviewed
scalar-query repair `5f1eeb29` and creation counterpart `4515d479`. These are
focused program results, not new native or Fresh acceptance.

Scalar conditions now use actual property metadata for root `--where-field`
and related matching/count/any/all views. The complete bounded source and
relationship transforms precede the native predicate and final root limit.
Unknown field authority remains distinct from an empty matching set. Initial
affected checks passed 248 in 100.84s; a later selection-budget change passed
11 directly affected checks in 4.94s. Independent review then found four real
defects: an advanced-root cap could become1000, incomplete metadata discovery
could select an ambiguous field, source removal could raise KeyError, and
related selected-value disagreement could go unchecked. All60 five-version
counterexamples failed before repair (16.64s), then passed (11.95s). Final
selected scope/type/reducer/page/older-source controls passed111 in81.28s.
These selections overlap; none is a full-suite or distinct-case total. Main
reviewed the immutable repair and its original logs without repeating green
checks. Original evidence is retained in `r77-query-field-program-logs` and
`r77-query-field-repair-logs` below the ignored full-coverage evidence root.
Reference/local/override predicates and record/function variants remain #181.

Creation now admits ordinary no-collision compound set graphs and preserves
the original standalone object.create planned-reference operation across all
five versions. Actual native-chosen names/GUIDs are bound by class, parent and
membership before dependent reference writes; no suffix or result-order guess
is used. The2021 create route uses closed setReference stages, never object.set.
Native stages/results stay separately retained, with independent final effects
and preservation checks. Existing-only compound children keep their original
route; creation-only children disclose one actual write and no dependent stage.

The no-collision source/history selection passed8 in56.47s; the five-version
original create caller and affected guards passed34 in42.98s. Main review found
missing/incorrect creation-only stage disclosure; its original RED is retained
and the corrected public source/history positive passed1 in9.91s. Counts overlap.
Handoffs, selected logs and review are hash-archived in
`r78-compound-program-logs`. No native witness is claimed for these new staged
behaviors. Multi-root collisions, duplicate requested sibling names, richer
graph forms and native-name create history remain #178/#192 work.

The first prepared scalar-query native node ran on macOS Console2025.1.7.9143
at `f6f1f28e` and failed in9.51s. The independent baseline and initial related
query succeeded, but the test wrapper prepended `--timeout30` to the Gateway's
complete pagination continuation; the Gateway rejected that altered command.
The detailed diagnostic document also contained4128 entries, making full paging
inappropriate for this small acceptance flow. This is no native acceptance PASS.
Its original root `r77-query-fields-f6f1f28e-2025-r1` retains85 hash-checked native
packets, three public invocations, zero transactions, unchanged source hashes/
mtime/tree, clean process teardown and a quarantined sandbox. The2021 attempt
was deferred pending a test-only correction; the failed root is not reused.

The test-only correction `aa82ea1e` uses compact business replies and a passive
capture of actual Gateway dispatch inputs, linked to the unchanged original
native packets. Complete returned continuations execute verbatim. On frozen
`d4183c6a6942f38cf07d9ab4f66fec928cc46b2a`, the same five-group read-only workflow
passed2025.1 in6.02s and2021.1 in9.37s. Each made five public queries, captured119
native packets and created zero transactions. Independent child order/values,
actual Pitch metadata, related matching/count/empty-root preservation and complete
root scope before native WHERE/final take1 all passed. All packet hashes and
actual dispatch associations, source integrity and cleanup were checked; passing
sandboxes were deleted by the existing lifecycle. See
`r77-query-fields-native-review-2021-2025.json` and each original root review.

The2022–2024 native matrix was not repeated for this shared predicate mechanism;
matching source and program checks still cover all five versions. The two real
runs do not establish every scalar kind, heterogeneous predicate, reference mode
or record/function variant. Original2025 fixture FAIL remains unchanged.

No Fresh, Windows native, full Program or full Non-live gate ran for this
increment. The PR remains draft and all affected functional tickets stay open.

## 2026-10-23 R78 Bed Mixer condition acceptance

No runtime change was needed. Four-version public ShareSet setup/edit checks,
existing policy alternatives and the 2021 constructor boundary passed 17 focused
tests in 5.99s. The original four fixture failures (missing requested stored-field
projection in a fake client) and corrected result are retained in
`r78-bed-program-logs`; five files are hash-archived with their handoff/source plan.

Frozen `df9af555619219b430c33b43f4392f91ebc08bae` passed one native workflow on
each matching macOS Console: 2022.1 = 9.79s, 2023.1 = 10.03s, 2024.1 = 10.44s,
2025.1 = 10.08s. Each has 25 independent observations, 115 hashed native packets
and two separately authorized verified transactions. A standalone Bed Mixer
ShareSet is created with policy1 only; its existing limit is then changed64→128.
Every parameter read, setup, edit and verifier uses the same actual nonzero
platform. Actual scalar metadata/enabled state, all four plugin parameters,
identity/notes, WorkUnit membership, parent and existing RoomVerb peer are checked.
Source integrity and cleanup passed; no audio rendering is claimed.

Evidence: `r78-bed-mixer-native-review.json` and
`r78-bed-df9af555-<year>-r1/root-review.json`. Matching 2021 captured host catalog
and primary plugin corpus contain no Bed Mixer class, and its constructor
backend is separately unavailable in the pinned function surface. No 2021 Bed
case ran or received PASS credit; this is a scoped host/version boundary, not
universal absence on every possible host. The source rationale remains in the
archived plan. No Fresh, Windows, Authoring or full gate was added. #177 and the
broader construction/plugin tickets remain open pending their full criteria.

## 2026-10-23 R76 sequence and R77 Time native acceptance

The R76 closed sequence workflow passed on all five pinned macOS Console
builds at frozen `c98ccf574a6d82380046a56df53f7e5eef34ce26`:

| Version | Result | Public reads | Native packets | Transactions |
| --- | --- | --- | --- | --- |
| 2021.1 | 1 passed, 9.65s | 7 | 155 | 0 |
| 2022.1 | 1 passed, 9.20s | 7 | 155 | 0 |
| 2023.1 | 1 passed, 9.04s | 7 | 155 | 0 |
| 2024.1 | 1 passed, 8.57s | 7 | 155 | 0 |
| 2025.1 | 1 passed, 9.19s | 7 | 155 | 0 |

Independent child identities/order/Volume/Pitch/class anchor first, last,
index, ranges, custom metadata scope, derived count/any/all/empty values,
ordered combination and repeated occurrences. An exact repeated business result
checks stability. No extra paging invocation was needed. All packet hashes,
source integrity and teardown checks passed. Evidence:
`r76-query-sequence-five-version-native-review.json` and
`r76-query-sequences-c98ccf57-<year>-r1/root-review.json`.
This is selected sequence acceptance, not every native predicate or record type.

R77 adds test evidence, with **no runtime change**. The public fake setup/edit
flow uses actual Time class 5111824 and matching five-version definitions;
18 affected checks passed in 7.19s. Earlier runs overlap and original fixture
failures are retained in `r77-time-program-logs` (nine archived files).
The native workflow separately creates a standalone Time Modulator with only
TimeModLoops=50, then edits its existing EnvelopeStopPlayback from true to false.
Live scalar metadata/enabled state, loops, Duration, notes, identity, parent,
peer Envelope values and complete WorkUnit membership are checked.

| Version | Frozen candidate | Result | Observation reads / native packets | Verified transactions |
| --- | --- | --- | --- | --- |
| 2021.1 | `0070be26` | 1 passed, 9.25s | 25 / 115 | 2 |
| 2022.1 | `0070be26` | 1 passed, 8.79s | 25 / 123 | 2 |
| 2023.1 | `0070be26` | 1 passed, 9.78s | 25 / 123 | 2 |
| 2024.1 | `0070be26` | 1 passed, 9.40s | 25 / 123 | 2 |
| 2025.1 | `0070be26` | 1 passed, 5.98s | 25 / 123 | 2 |

2021 omits currentPlatformId: both live fields explicitly certify unlink=false,
so the enabled observation uses the existing null-GUID read convention and the
mutation omits platform. Later versions use the actual disclosed platform.
All source/packet/cleanup checks passed. Evidence:
`r77-time-five-version-native-review.json` and per-root reviews. These are the
representative count-50 existing edit and minimal setup, not every numeric
endpoint, conditional constructor combination or complete Time/Bed Mixer family.
No Fresh, Windows, Authoring or full Program/Non-live gate was added.

## 2026-10-23 R75 positive device fixture and R76 sequence queries

The positive master-bus workflow uses a new owned copy of the currently assigned
System device. Closed `object.copy` and `object.setReference` each receive their
own preview, authorization, execution and verification. Independent reads prove
the copied plugin identity and five actual selected-platform parameter values,
the changed reference, and preservation of observed devices, peers and topology.

| Console version | Frozen candidate | Result | Observation reads / native packets | Verified transactions |
| --- | --- | --- | --- | --- |
| 2024.1.13.9056 | `987b0702` | 1 passed, 10.47s | 38 / 152 | 2 |
| 2025.1.7.9143 | `93c339bf` | 1 passed, 7.00s | 38 / 152 | 2 |

Both source trees remain unchanged and passing sandboxes were cleaned. Exact
packet hashes, observations and lifecycle checks are bound in
`r75-system-copy-native-review.json` and the per-root `root-review.json` files.
The first 2025 attempt at `987b0702` failed before any transaction because its
test assumed two siblings; the committed 2025 fixture contains four. The repair
requires the selected bus and peer, rejects duplicate GUIDs, and preserves all
observed sibling rows/order. Original FAIL (8.36s, 11 reads, 22 packets) and
quarantine remain retained. The valid 2024 effect was reused, not rerun.
The earlier No_Output rejection remains indeterminate and was never replayed.
These positive System-copy results do not establish arbitrary plugin eligibility.

R76 sequence queries are integrated at `93fc2467`: closed filtering, ordered
first/last/index/ranges, count/existence/all-match and concatenation reuse the
existing related-output planner. Output explicitly identifies Gateway-derived
sequences rather than claiming native function-return equality. Matching pinned
source sections distinguish SELECT transformations from return expressions.
The original affected selection passed 235 in 30.53s. Review found a discarded
finite prefix before a later filter and a custom field colliding with an internal
reducer marker. Both reproduced through the public Gateway and were repaired;
70 affected controls passed in 16.31s (overlap with the earlier selection).
Independent correction review found no further actionable issue. Twenty-six
original log/handoff/review files are hash-archived in
`r76-query-sequence-program-logs`; these original runs are program evidence; subsequent native sequence acceptance
is recorded above. Neither is a full gate. Record lists, metadata-bound comparison predicates,
randomizer and remaining versioned query functions stay assigned to #181.

## 2026-10-23 R75 reference applicability and R76 structural history

R75 candidate `3898c8ad98253bdf49a8ae253073e0e720d5ad3c` replaces invalid
reference-enabled probes with a source-bound topmost-Bus ancestry proof at Field
binding/refresh, preparation, prewrite and verification. Scalar enabled-state
checks remain. Focused final affected controls passed 69 in 12.95s; strengthening
the fixture to existing System → distinct No_Output then passed 47 in 12.09s.
These overlap. All 149 machine-contract seals remain unchanged; fourteen
operation guidance lanes and five property-state disclosures changed. Twelve
original log/schema files are hash-archived in `r75-reference-program-logs`.

The 2024 native attempt `r75-master-bus-3898c8ad-2024-r3` reached one authorized
`setReference` dispatch after structural checks, then received
`ak.wwise.invalid_reference`. Original result: **1 failed in 10.01s**.
Transaction `tx1-k7dva2jtg0mmvr1jvtgj` remains **indeterminate**: twelve public
observation commands, 58 native packets, no reference `isPropertyEnabled` call,
and no post-dispatch verification. Its journal, observation, packet hashes and
source/cleanup checks are bound by `root-review.json`. The failed sandbox is
quarantined; never verify or replay this transaction. The source project is
unchanged. Matching plugin source identifies a `CanBeMasterSink=false` target
restriction for No Output; its exact role applicability is under diagnosis.
That original attempt provides no successful reference-effect credit; the subsequent positive fixture below is separate evidence.

R76 structural property history is implemented at `988e60b1`, integrated with
R75 at `c08ca046f3c28052ae1e83535f42ede677106fc0`. The existing receipt observer
now accepts the tagged Switch-child proof without inventing native type, checks
metadata/association conditions and typed values, and admits a certified
nonlinkable omitted-platform view. Undo remains pinned to 2022–2025 and redo
to 2023–2025. No global history-stack identity or automatic retry is claimed.
Focused structural/context tests passed 152 in 100.34s; existing ordinary
scalar/reference/policy/nonretry callers passed 37 in 25.51s. An additional
zero-GUID platform boundary passed one in 0.81s; three post-merge shared-caller
checks passed in 3.60s. Overlapping earlier runs and original fixture failures
are retained in `r76-history-program-logs`.

The selected structural history workflow passed at frozen `9a055665` on
2022.1 (10.52s, source change and undo, native type omitted) and 2023.1 (10.61s,
source change, undo and redo, native type present). Both force tagged structural
binding. They use 21/26 independent observation reads, 130/167 native packets,
and 2/3 separately authorized verified transactions respectively. ContinuePlay,
FadeInTime, owner, child and ordered membership are checked after each phase.
Source integrity and cleanup passed. Evidence: `r76-structural-history-native-review.json`
and `r76-association-history-9a055665-<year>-r1/root-review.json`.
The same tagged source/undo/redo workflow then passed on 2024.1 (10.49s)
and 2025.1 (10.22s) at frozen `bb0e5bea`. Each has 26 observation reads,
167 hashed native packets and three verified transactions, with unchanged source
and clean teardown. These resolve the exact later-version association reversal
outcome that generic history and source-write component evidence alone could not
prove. The 2022/2023 witnesses were reused without rerunning. The combined
`r76-structural-history-native-review-2022-2025.json` binds all four original
candidates/results. Wwise 2021 retains its pinned history API boundary.
This proves the selected outcomes, not a global stack head or unobserved state.
#177 and #192 stay open; no Fresh or full-gate result is added.

## 2026-10-23 R74 related list native acceptance

Frozen candidate `e48bfcc378f8404b80f4ed1b7e959ed4a177f32c` passed the
root-preserving child-record workflow on all five pinned macOS Console builds:

| Version | Selected result | Native packets | Strategy |
| --- | --- | --- | --- |
| 2021.1 | 1 passed, 9.55s | 31 | Owner-specific relationship queries and GUID-keyed value reads |
| 2022.1 | 1 passed, 9.40s | 31 | Owner-specific relationship queries and GUID-keyed value reads |
| 2023.1 | 1 passed, 4.70s | 15 | Native composed member records |
| 2024.1 | 1 passed, 4.18s | 15 | Native composed member records |
| 2025.1 | 1 passed, 4.67s | 15 | Native composed member records |

Each case uses three read-only public commands. The container remains the root;
five child GUIDs, their native order, Volume and metadata-bound Pitch agree with
raw packets and an independent fixed-field children query. Repeating the root
query returns the same values. All fifteen commands succeeded, with zero
transactions, unchanged source hash/mtime/tree inventory, clean process teardown
and deleted passing sandboxes. Original packet hashes and observations are
bound in `r74-lists-e48bfcc3-<year>-r3/root-review.json`; the local aggregate is
`r74-five-version-list-native-review.json`.

The older implementation uses documented SELECT membership and positive-offset
skip windows, never a bare list return accessor or `skip 0`. The latter caused
the separate original 2021 failure at `6af29be7` (1 failed, 8.47s, zero writes).
The 2023 original case on that candidate first proved native composed values,
then failed at a test-only unsupported relationship/custom-field combination
(1 failed, 8.42s, zero writes); the independent oracle now uses the existing
fixed `pitch-cents` output. Both original verdicts and quarantines are retained.

Focused repair evidence includes twelve passing first/positive-window,
overflow and origin-page controls in 17.66s; earlier affected page reconstruction
passed five in 19.30s and caller checks passed 27 in 15.88s. These overlap and
are not a full gate. Page fitting reduces the number of unchanged entries,
preserving absolute offsets, values and existing output limits. The native
workflow proves the selected child-list path, not every list relation, function
or pagination branch. Remaining query functions stay in #181. No Fresh,
Windows, Authoring or full-gate result is claimed.

## 2026-10-23 R74 list and R75 master-bus native findings

The list implementation and test-only master-bus corrections were combined at
`f5ecfd8240ac4f1cd87820ba63385a27a21b201b`. The list review repaired origin
diagnostics changing between result pages and unchanged native extensions
being mistaken for scope drift. Focused correction selections passed 14 in
0.98s, 17 in 10.96s and 27 in 49.13s; these overlap and are not a full gate.
Twenty original program logs, including failures, are hash-indexed under the
local full-coverage `r74-list-program-logs` directory.

Native observations remain failures, with no mutation or acceptance credit:

| Root / candidate | Original result | Finding |
| --- | --- | --- |
| `r75-master-bus-0b9a0dc8-2024-r1` / `0b9a0dc8` | 1 failed, 7.30s | Test assumed the base AudioDevice class for plugin instances; matching catalogs and native packets instead prove System 11403271 and No Output 11862023. Native reference metadata uses the label `Audio Device`. Test-only repair preserved exact identities. |
| `r74-lists-f5ecfd82-2021-r1` / `f5ecfd82` | 1 failed, 8.20s | Wwise rejected `children` as a return accessor before returning members. The older-version strategy requires documented relationship-query semantics; this is unfinished interface support. |
| `r75-master-bus-f5ecfd82-2024-r2` / `f5ecfd82` | 1 failed, 7.35s | Reference metadata discovery succeeded, but native `isPropertyEnabled(AudioDevice)` reported that the property did not exist. Property-versus-reference applicability must be resolved before another attempt. |

The three roots respectively contain 9, 1 and 12 public invocations, zero
transactions, unchanged source hashes/mtimes/tree inventories and clean process
teardown. Their failed sandboxes remain quarantined. Each root's
`root-review.json` binds the original observation and packet evidence. Other
versions are held pending diagnosis, not counted as tested. #177 and #181 retain
the intended master-bus reference effect and five-version list requirements.
No new Fresh, Windows, Authoring or full-gate result is claimed.

## 2026-10-23 R74 Switch-child property identity support

Candidate `e53b15e380ac05a58ee86c57462c882bf8d6e922` adds a closed
`draft-bind-switch-child-context` target for `object.setProperty`. Normal owner
and child handles establish the documented context edge, reverse owner and
version-pinned class/source proof. The tagged target preserves native type
omission and revalidates its proof at discovery, preparation, execution and
verification. Ordinary incomplete-ID binding stays rejected. Live metadata
authorizes scalar fields; the implementation is not limited to ContinuePlay.

Focused program selections passed 55 in 16.71s and 112 in 26.03s before the
final early-discovery guard correction. The failing discovery/continuation
nodes were repaired and passed; final ordinary schema, materializer, discovery,
formal receipt and history-boundary consumers passed 20 in 1.15s. The exact
overlapping selections and original failure-to-fix mapping are retained in
`r74-association-program-logs/waapi-r74-association-implementation.md`; all
seventeen original logs were hash-checked and preserved. Five setProperty
schema lanes changed; the other 144 reviewed schema digests remain identical.

One real macOS Console case per older version passed on the same candidate:
**2021.1: 1 passed in 9.06s; 2022.1: 1 passed in 8.30s;
2023.1: 1 passed in 4.72s; 2024.1: 1 passed in 4.23s**. Native 2021/2022
association rows omit type and use the new structural target. Native 2023/2024
rows report ObjectSettingAssociation and use the ordinary typed route.
Each run makes one separately previewed, authorized, executed and verified
ContinuePlay false-to-true change, with sixteen public observation commands.
Independent readback preserves FadeInTime, owner state, the child and ordered
child/context membership. Packet counts are respectively 91, 93, 75 and 75;
all recorded hashes match. Source content/mtime/tree metadata are unchanged,
process cleanup completed and passing sandboxes were deleted.

Evidence under `.waapi-skill-state/full-coverage/`:
`r74-association-e53b15e3-<year>-r1/root-review.json` and
`r74-association-native-review.json`. The original R73 failures stay unchanged.
The previously proven 2025 ordinary route at `e3f22460` is reused, not rerun
or relabeled as same-candidate structural-route evidence. Structural targets
with present native type have program proof, not an extra 2025 native run.
Structural history recovery remains explicitly unavailable and assigned #192;
Fresh discovery of the new route is unproven and no Fresh budget was spent.
Other condition mechanisms and full #177 acceptance remain open.

## 2026-10-23 R72 scoped multi-hop query outputs

Candidate `f9c3e81325ae7a64209337de2b22484652c7ee43` extends the closed
related-output path with multiple singleton relations, metadata-bound custom
terminals and resolved/local reference hops. Actual related class or exact
object metadata owns field selection; root order, identity and observed path
scopes are revalidated. Existing projection limits and sealed paging apply.
Root review corrected typed scope equality, native extension preservation and
exact-object fallback when class metadata cannot establish a field's kind.

Focused program evidence includes 400 passed in 54.20s before the final
preservation and review corrections. Subsequent affected selections passed
92 in 8.97s, 35 in 3.23s, 90 in 4.65s and 62 in 4.50s. These overlapping runs
are not additive or a post-fix full-gate result. Original RED logs and exact
commands remain in `r72-program-logs/waapi-r72-implementation.md` under the
retained full-coverage evidence root.

The same final candidate passed one combined read-only case per pinned macOS
Console version: **2021.1: 1 passed in 4.97s; 2022.1: 1 passed in 8.44s;
2023.1: 1 passed in 4.16s; 2024.1: 1 passed in 3.91s;
2025.1: 1 passed in 4.09s**. Each case uses four public queries: AudioFileSource
through its Sound and container, an independent Sound read, an independent
resolved Bus read and a repeated source read. Assertions prove the two-hop
container Volume, scoped Pitch, local versus inherited OutputBus, reference-hop
Bus Volume and actual Sound class metadata scope while preserving root identity.

All five final category records are PASS, with zero transactions, unchanged
source hashes/mtime/tree metadata, clean process shutdown and deleted passing
sandboxes. Each root retains twenty native packets and an independently checked
root review. Evidence: `.waapi-skill-state/full-coverage/`
`r72-related-paths-f9c3e813-<year>-r1/` and
`r72-five-version-native-review.json`. No Fresh, Windows, Authoring or full gate
was added. List composition, functions, legacy spellings and other outstanding
query obligations remain #181 work; this is not whole-ticket completion.

## 2026-10-23 R73 older association identity observation

Two targeted macOS Console **2021.1.14.8108** attempts remain failed,
with zero transactions. At `1085ff19`, **1 failed in 9.18s** after a successful
status read: the test required currentPlatformId, which native status omitted.
Test-only `00d9bebf` uses the existing null-GUID enabled-read convention and
omits mutation platform only when that status key is absent and both live
scoped fields prove `supports.unlink=false`. Present invalid platform values
still fail; the proven 2025 explicit-platform path is unchanged.

The new attempt at `00d9bebf` retained **1 failed in 4.87s**, after five
successful public reads. The actual association returned GUID, class ID
1572880, owner, path and ContinuePlay/FadeInTime values, but omitted `type`.
The complete-identity gate stopped before Draft creation. This establishes a
version-specific interface gap, not native absence or mutation success.
Closed association/owner/child identity support remains #177 implementation
work; no type alias or general identity relaxation is inferred.

Both attempts preserve source content hashes, project mtime and tree metadata;
process cleanup completed and failed sandboxes remain quarantined. Original
category/observation files and checked `root-review.json` records are under
`.waapi-skill-state/full-coverage/r73-association-1085ff19-2021-r1/` and
`r73-association-00d9bebf-2021-r2/`. All eleven second-attempt native packet
hashes were checked. No 2022–2024 run, 2025 repeat, Fresh or full gate was added.

## 2026-10-23 R72 existing association ContinuePlay

The existing public `object.setProperty` path passed a targeted macOS Console
**2025.1.7.9143** case at `e3f224604f6e0672b192559eb34c39705b55bbd5`:
**1 passed in 5.23s**, one verified transaction. The test resolves the current
association GUID through Shells_Concrete's child-context output, rather than
reusing an earlier sandbox's ephemeral GUID. Exact object-scoped metadata
proves ContinuePlay is Boolean with an AssocParent/Enable dependency on
SwitchBehavior=1; the owner's real int16 metadata discloses Step=0 and
Continuous=1. Public property-state reads report enabled before and after.

The separately previewed and authorized edit changes only that association's
ContinuePlay from false to true. Independent readback preserves FadeInTime,
observed association identity/owner, the owner's settings, the original child
and the ordered child/context membership. Sixteen public observation commands
(status, object queries and metadata reads) supplement the Draft transaction
phases. All 75 retained native packet hashes were checked; final category is
PASS, source hashes/mtime/tree metadata are unchanged, processes are cleaned
and the passing sandbox is deleted. No runtime fix was needed.

The original attempt at `e46ac6ea` retained **1 failure in 6.23s**, five
successful reads and zero transactions. Its test incorrectly required explicit
`parent:null`; the current query preserves native omission and reports
`unavailable_fields:["parent"]`. The test-only repair keeps absence and null
distinct and preserves exact before/after snapshots. That original FAIL and
quarantined sandbox remain unchanged; its read observations are retained, but
it grants no mutation credit.

Evidence roots under `.waapi-skill-state/full-coverage/`:
`r72-association-e46ac6ea-2025-r1/` and
`r72-association-e3f22460-2025-r2/`, each with original category/observation files
and `root-review.json`. Test inspection receipts are in
`r72-association-program/`. Other-version association identities/applicability
remain assigned #177 work; this is not five-version native effect, atomic
object.set, Fresh, Windows or whole-ticket acceptance.

## 2026-10-23 R72 Parent/Show Weight evidence reuse

Read-only review of the five original Parent/Show roots at
`5d899f1e30d42422fbd04c07ebb3490252a7477f` found sufficient native business
evidence for the exact existing Sound.Weight condition. Ten original Weight
transactions (two modes per version) retain matching immutable artifact hashes,
confirmation tokens, one execution each, successful guards and independent
readback. Sequence mode 0 changes Weight 50 to 37; Random mode 1 changes 37 to
38. Each Weight edit preserves the parent mode and the other observed source
fields. Metadata remains equal before/after, and isPropertyEnabled is true in
both modes. All five original lifecycles are PASS with unchanged source hashes
and mtimes, no recorded errors and completed cleanup.

The original `agent_semantic_pass=false` values remain unchanged: these runs
never claimed Fresh Agent acceptance. Exploratory provenance and the absence
of newer category wrappers do not erase their actual authorization, effect and
cleanup evidence. This assessment grants no new run or modern producer receipt.
It withdraws the proposed five replacement native tests.

The property builder/value validation and Real64 comparison retain their
relevant ASTs. Current Show validation and metadata/identity/platform guards
strengthen preparation without changing this native property effect. On current
candidate `d1c4866d`, the directly affected public Parent/Show function passed
**18 tests in 5.02s**, covering both modes for setProperty on all five versions
and object.set on 2022.1–2025.1. This is focused program evidence, not another
native batch or full gate.

Exact five product IDs, ten transaction/artifact hashes, observation/lifecycle
hashes and source review are retained under
`.waapi-skill-state/full-coverage/research/` in
`waapi-r72-parent-weight-native-reuse.md` and
`waapi-r72-parent-weight-reuse-audit.json` (SHA-256
`214be9d4bd7ef38ca0988960f4bcce72f6fc95134b3f404d73ba19710b852db2`).
The current program log is `r72-parent-current-program.log` in the parent state
directory. Exact source/evidence linkage remains #195 work; missing linkage
must not be relabeled as missing native effect. Other condition mechanisms,
unobserved sibling/global state and whole #177 completion are not claimed.

## 2026-10-23 R71 related fixed outputs

Candidate `fd1c139e44e3fd39870d5fb3c6456a281a6be86a` adds
`--include-related RELATION BUSINESS_OUTPUT`. The closed parent/owner/work-unit
relations share one projection record with source-reviewed fixed outputs and
version-specific descriptors. Root identities remain unchanged; related values
and their native object reference appear in a separate group. Fixed related
outputs require no property metadata lookup. Existing output budgets, native
limits, platform/language scope and sealed lossless pages remain enforced.

Matching SDK descriptor/chain rows are packaged for all five versions. The new
142 fake-client controls were resolved through focused selections, not one
combined all-green run: five initial positives passed in 0.44s; the expanded
selection retained 101 passes and five budget-message failures in 1.72s, then
the corrected message passed those five in 0.44s. Twenty-six list-valued output
and paging controls passed in 2.76s; 35 affected existing caller checks passed
in 1.33s. The final seven source/schema checks passed in 0.53s, including the
corrected 2024 SDK descriptor row. Original REDs, intermediate failures and exact
commands remain in `.waapi-skill-state/full-coverage/r71-program-logs/`.

Sequential macOS Console runs on this same candidate passed:

| Version/build | Result |
| --- | --- |
| 2021.1.14.8108 | 1 passed in 4.57s |
| 2022.1.19.8584 | 1 passed in 4.31s |
| 2023.1.19.8928 | 1 passed in 4.06s |
| 2024.1.13.9056 | 1 passed in 3.79s |
| 2025.1.7.9143 | 1 passed in 4.57s |

Each performs three read-only queries: the Sound with parent outputs, an
independent exact-parent read, then a repeated Sound read. All five distinguish
the Sound's local Volume/Pitch (0/0) from FS_Concrete's (-12/-560), preserve both
identities, and match native packets to public projections. Total: fifteen
reads, zero transactions. Final categories are PASS, sources remain unchanged
and all owned processes/sandboxes are cleaned. Roots:
`r71-related-fd1c139e-<version>-r1/` under the same state directory, with original
packets and `root-review.json`; aggregate `r71-five-version-native-review.json`.

This proves the shared scalar parent projection and identity handling. It does
not claim separate native execution of every terminal or owner branch. Custom
related fields, multiple declared hops, list composition and unresolved native
outputs remain #181 implementation work. No new Fresh, full gate, Windows or
Authoring validation is claimed.

## 2026-10-23 R70 stored-reference clear and owned history

Candidate `23f5b5d70e797e2ecee348033fe8421bdf3eb9b5` fixes the nullable
`object.setReference` clear path. Its Preview binds the directly stored value
and resolved inherited context separately; drift checks preserve both, while
verification checks that the stored value was cleared. The public outcome
explicitly allows an inherited reference to remain effective. Ordinary non-null
reference assignment and its activation requirements are unchanged. Legacy
unexecuted clear Previews require a new Preview; executed or indeterminate
transactions are not reinterpreted or replayed.

The matching five-version nullable metadata and native reference result shapes
were checked before implementation. Focused fake-client selections cover all
five versions, hidden local/context drift, missing/malformed observations,
native JSON extensions, null identities, legacy state, authorization and owned
history consumers. The final extension/control selection passed **91 in
24.60s**; directly affected reference-presence, preservation and non-null
activation callers passed **60 in 15.94s**. Earlier producer/consumer controls
passed **35 in 2.01s**, targeted repaired/positive nodes **15 in 5.58s**, and
merged Preview/history checks **9 in 4.53s**. These overlap and are not a summed
fresh gate. Original REDs and intermediate failures remain in
`.waapi-skill-state/full-coverage/r70-program-logs/`.

One macOS WwiseConsole **2025.1.7.9143** workflow passed **1 test in 10.96s**.
It uses one isolated lifecycle, three separately previewed/confirmed/executed
and verified transactions (clear, undo, redo), and twelve independent reads.
The Sound's stored Thunders Attenuation becomes the zero GUID while inherited
Footsteps remains effective and OverridePositioning remains false. Undo
restores the original local reference; redo restores the cleared state. The
ancestor and peer remain unchanged after every step. Final category evidence
is PASS, source hashes/mtime/tree metadata are unchanged, processes are cleaned
and the passing sandbox is deleted.

Evidence: `r70-stored-clear-23f5b5d7-2025-r1/` under the same state root, including
original category records, observation packets and `root-review.json`. This
proves receipt-bound history effects on the observed objects, not global undo
stack ownership, preservation of unobserved project state, or a new automatic
rollback mechanism. Five-version R69 read evidence is reused for the stored vs
inherited distinction; it is not five-version clear/undo execution evidence.
No Fresh, broad gate, Windows or Authoring run is claimed. Remaining #177,
#181 and #192 obligations stay open.

Published candidate `3c19b324` subsequently ran the hosted pure-code preflight:
**825 passed / 1 failed in 46.39s** (run `39854162870`). Its only failure was
the reviewed operation-schema aggregate. Exact comparison of all 149 lanes
proved that only the five setReference null-target descriptions changed; the
other 144 remained identical. Test-only repair `89f26343` adds the new aggregate
and exact prior-lane substitutions while preserving all fifteen historical
aggregate assertions. The original failed node passed **1 in 0.37s**; an
intermediate historical-inverse failure is retained. Original CI logs, exact
schema deltas and the focused repair are archived in `r70-program-logs/` and
the adjacent `r70-published-ci-*` files. No native rerun was needed for this
test-contract correction.

## 2026-10-23 R69 directly stored reference values

Candidate `850b163b8b56298c3d4dfa88db41e83d2fc1f6fa` adds the closed
`--include-local-reference` mode, with fresh live reference discovery and
separate `local_references` results. Ordinary reference reads retain their
existing override-resolved behavior. The shared field-mode table preserves
property modes, result bounds, paging and exact terminal output. Matching
five-version SDK Return Options evidence is packaged with exact page/build
and section hashes; no installed SDK is required at runtime.

New fake-client controls ran as bounded selections: the expanded file retained
**105 passes / 15 test-fixture failures in 6.08s**; correcting parser/cap/inventory
fixture assumptions and rerunning only the affected parameterized functions
passed **75 in 3.40s**. The existing affected regression selection retained
**140 passes / 2 source-hash assertion failures in 4.68s**. Exact older-version
HTML hashes corrected those two guards (**2 passed in 0.34s**); the final
source-packaging guards passed **5 in 0.38s**. Together these selections resolve
the new 120 controls and affected existing checks; they are not a single fresh
combined all-green run. Original REDs, intermediate failures and exact commands
remain in `.waapi-skill-state/full-coverage/r69-program-logs/`.

Sequential real macOS Console cases all passed on the same candidate:

| Version/build | Result |
| --- | --- |
| 2021.1.14.8108 | 1 passed in 9.23s |
| 2022.1.19.8584 | 1 passed in 8.17s |
| 2023.1.19.8928 | 1 passed in 8.76s |
| 2024.1.13.9056 | 1 passed in 7.47s |
| 2025.1.7.9143 | 1 passed in 8.51s |

Each case performs five read-only queries on existing source-selected objects.
It proves that the Sound stores Master/Main Audio Bus and Thunders Attenuation
while resolving SFX and Footsteps Attenuation from its ancestor; its local
OverridePositioning remains false. Exact native packets and public groups agree,
the ancestor's values and both Bus identities are read independently, and the
Sound repeats unchanged. All final category records are PASS, with zero
transactions, unchanged source hashes/mtime/tree metadata, clean process
shutdown and deleted passing sandboxes.

Roots: `.waapi-skill-state/full-coverage/r69-local-reference-850b163b-<year>-r1/`;
each has `root-review.json`, original packet hashes and captured Attenuation
metadata. The aggregate is `r69-five-version-native-review.json`. The captured
nullable/inherited reference facts also support the separate clear-verifier
repair; they do not prove a clear mutation. No Fresh, full gate, Windows/Authoring
or inventory regeneration is claimed. Related-field projections and other #181
branches remain assigned work.

## 2026-10-23 R68 Blend Track output and field-refinement guidance

Candidate `f437f57cfa22cf03d0983be66dfc3864940a00c0` exposes the fixed
`query-object --include blend-tracks` output on the source-proven 2024.1/2025.1
lanes. Its schema cites the matching return-expression enum, native addTrack
read guidance and object-return pattern union. It does not invent a narrower
accessor-specific schema. Earlier versions retain an explicit unavailable
packaged route, not a claim of native absence.

The selected fake-client run passed **169 tests in 8.25s**: versioned discovery
and dispatch, unchanged native order/extensions, false/zero/empty/null/absence,
advanced-query composition, duplicates, bounded result paging and result drift.
The same batch repairs custom-field refinement guidance to retain the originally
requested ordinary/override-source mode. No-match followed by refinement proves
the intended native accessor remains selected. The output audit now accounts
for return-expression enum entries as well as named result properties; new
unclassified enum entries fail the check. Legacy spelling reconciliation,
2025 `states` semantics and the native spelling conflict remain explicit #181
questions rather than assumed equivalences or automatic public inputs.

Sequential native macOS Console runs on that same candidate each passed once:
**2024.1.13.9056: 1 passed in 7.40s**;
**2025.1.7.9143: 1 passed in 8.74s**. Each reads an existing Blend Container's
track list, independently resolves both exact track GUIDs, then reads the owner
again. Original native packets and public output agree on the On-Load/Off-Load
track identities, names and order. All four reads per version completed; there
were no transactions. Source hashes/mtime/tree metadata were unchanged, process
shutdown was clean and the passing sandbox was deleted.

Evidence roots: `.waapi-skill-state/full-coverage/r68-blend-tracks-f437f57c-<year>-r1/`,
with per-root `root-review.json` and aggregate `r68-two-version-native-review.json`.
Observation SHA-256 values are
`1ded5b8c706ac15f4b492d1357575a77de4cefdcf4e5af60808fd94c6194fc9a`
and `475a47855caba9c8837b612baf649d82ff356660631227f4ec840b9e9c11388c`
for 2024 and 2025 respectively. Original RED/intermediate audit failures and
final code-test stdout remain in `r68-program-logs/`; they were not regraded.
No new Fresh, broad gate, Windows/Authoring, inventory regeneration or historical
source-evidence rebinding was performed. R67's native property results remain
valid without rerunning them for the refinement guidance change. #181 stays open.

## 2026-10-23 R67 property values at the source of override

Candidate `29cb2291ba87d67c1058dae6f5e77c106c25c302` adds the closed
`query-object --include-override-source-value` option. Ordinary property values
and values at their source of override can be requested together and remain in
separate result groups. The Gateway owns native accessor construction; this is
not ancestor identity or a runtime RTPC/audio result.

Five-version fake-client controls cover exact dispatch, disclosure provenance,
false/zero/null/absence, metadata scope, invalid declarations, duplicate output
aliases, paging and continuation drift. The affected four-file run retained
**623 passes / 2 stale baseline assertion failures in 77.62s**. Correcting only
the old 2021 diagnostic-message expectations and running the failed/new/directly
affected selection produced **127 passes in 4.71s**. Original logs and source
notes are preserved under `.waapi-skill-state/full-coverage/r67-program-logs/`.

The same read-only native test ran sequentially on five independently owned
macOS Console sandbox copies, all on that single candidate:

| Version/build | Result |
| --- | --- |
| 2021.1.14.8108 | 1 passed in 8.71s |
| 2022.1.19.8584 | 1 passed in 8.40s |
| 2023.1.19.8928 | 1 passed in 8.43s |
| 2024.1.13.9056 | 1 passed in 7.93s |
| 2025.1.7.9143 | 1 passed in 5.02s |

Each case reads the child Sound, its parent and the same child again. Native
packets and public results independently retain child `3DSpatialization=0`,
`OverridePositioning=false`, and source-of-override value `2`; the parent's
own and override-source values are both `2`, with its override enabled.
All final category records are PASS, with no transactions, unchanged source
hashes/mtime/tree metadata, clean process shutdown and deleted passing sandboxes.
Exact roots are `.waapi-skill-state/full-coverage/r67-query-override-29cb2291-<year>-r1/`;
the per-root `root-review.json` and aggregate `r67-five-version-native-review.json`
pin original observations and hashes. No Windows, Authoring, Fresh or full-gate
evidence is added; #181 remains open for its other query branches.

## 2026-10-23 R66 existing-field metadata and staged PlaylistSlot edits

Public fake-client tests reproduced a shared `object.set` omission: metadata
without activation dependencies was not retained for execution/verification
drift checks. The ordinary reference controls produced **8 failures / 4 passes**
across 2022.1–2025.1, then **12 passes** after using the existing guard for every
consumed field. At `99d31eca`, the selected final run passed **41 in 13.20s**,
including ordinary scalar/reference drift, notes-only changes without metadata
queries, conditional callers and the native 2021.1 operation boundary.
Original focused logs are retained in
`.waapi-skill-state/full-coverage/r66-compound-program-logs/`.

The simulated direct PlaylistSlot `object.set` success did **not** establish
native support. The first native attempt at `99d31eca` failed in the test helper
before a transaction: it assumed the wrong field-discovery projection
(1 failed in 5.63s). Reusing the existing projection helper passed its two
controls in 0.51s. The second native attempt at `c770e807` reached `object.set`
and was rejected by Console 2025.1.7.9143 with `ak.wwise.unexpected_error`,
`objectType: 50`, and `Can't process object type` (1 failed in 5.57s).
Transaction `tx1-dbdr5e98xjqb8szgr6ye` remains indeterminate; it was not verified
or replayed, and no unchanged sandbox write outcome is inferred. Both original
FAILs and quarantined sandboxes remain preserved. These observations do not
establish absence of every possible owner-list or other-host update form.

Candidate `eba0e2bb` then completed the business outcome through existing
`object.setNotes` and `object.setReference` routes: **1 passed in 7.69s** on
Console 2025.1.7.9143. Each stage had a separate immutable Preview, authorization,
execution and verification; the second Draft rebound the independently observed
post-notes object. Sixteen bounded query observations proved exact final notes
and reference, unchanged peer, ordered list membership, owner and target.
Both transactions reached `verified`; source hashes/mtime/tree metadata were
unchanged, processes exited cleanly and the passing sandbox was deleted.
This is a two-step workflow, not an atomic `object.set` success.

The reviewed final code at `0534b7ca` withdraws the direct-slot admission and
its simulated success expectations. It retains the generalized metadata guard
and rejects direct existing-slot `object.set` before Preview with a scoped
diagnostic and the separately previewed alternative. Final affected checks
passed **44 in 12.68s**; the final guidance/zero-write controls passed **9 in
1.71s**. The existing standalone reference helper is unchanged from R64.

Original native roots are under `.waapi-skill-state/full-coverage/`:
`r66-playlist-compound-99d31eca-2025-r1`,
`r66-playlist-compound-projection-2025-r2`, and
`r66-playlist-staged-eba0e2bb-2025-r3`. The final observation SHA-256 is
`ca7568395c684d551dd2d55cf4916ea1cc5c03c1a5533a63b50806c9180f71be`.
No Fresh, broad gate, inventory regeneration or historical evidence rebinding
was performed for this runtime slice. #177/#178/#180 and consolidated #195
acceptance remain open; no whole-ticket or whole-goal completion is claimed.

## 2026-10-23 R64 existing PlaylistSlot reference change

Candidate `ee55f8e5` passed one public-Gateway mutation on macOS Console
**2025.1.7.9143: 1 passed in 6.04s**. The existing unnamed PlaylistSlot was
bound by its exact native class, its `PlaylistObject` field was discovered,
and one separately previewed and authorized transaction changed its reference
to a direct child of the owning RandomSequenceContainer. Thirteen independent
bounded query observations established the requested target, unchanged peer,
unchanged list order/membership, and unchanged owner and target identities.
The transaction reached `verified`; source hashes, mtime and tree metadata
were unchanged, the process exited cleanly, and the passing sandbox was deleted.

Original log, final lifecycle record, observation and Root review are retained
under `.waapi-skill-state/full-coverage/r64-playlist-effect-ee55f8e5-2025-r1/`.
The observation SHA-256 is
`52b157ba15d0f98949ef03c1bdb24e0e19bac4104e0b78bc485fe99a9d5ee1a6`.
The fixture's separate Authoring-host boundary grants no Authoring coverage.

At `23008fa31`, affected fake-client tests passed **1291 in 290.24s**, including
55 new Playlist cases. This result is retained as an explicitly transcript-derived
receipt (`r64-playlist-23008fa31-focused-transcript-receipt.json`); original stdout
was not saved to a file. Review then reproduced an unproved rename reaching a
Preview. A class-specific `OBJECT_NAME_MUTABILITY_UNPROVEN` guard at `ee55f8e5`
passed **19 focused checks in 1.55s**; the original RED and final logs are retained
under `.waapi-skill-state/full-coverage/r64-playlist-rename-*.log`.
That guard does not claim Wwise prohibits renaming this class.

No full Program/Non-live, Fresh or older-version native gate ran for this slice.
The 2023/2024 list-level variants, new-slot construction and unproved name
semantics remain work under #177/#178/#180. This result closes only the tested
existing-slot reference outcome; it does not close any of those tickets or
refresh historical branch-completion evidence automatically.

The follow-up interface-inventory check found older unreconciled seals. Extracted
contracts are identical at `ee55f8e5`, `518edce3` and `09ae4b8e`; the Playlist
slice adds no contract-row drift. The prior difference from policy `c5b93c31`
is 13 operation rows, two parser rows and one Topic continuation row, with no
added/removed rows. A provisional interface regeneration succeeded in a separate
worktree, but dependent branch generation failed on the historical Source
attachments: all five versions have the same five changed runtime-file hashes
among 547 source keys. The incomplete reconciliation is not merged or counted
as a passing inventory check. Preserve the original evidence; consolidate the
source review and dependent inventories once the runtime batch settles, before
the required final gates under #195. No native recapture was performed for this
bookkeeping failure.

## 2026-10-21 R62 targeted PlaylistSlot metadata observation

Candidate `7572b2d7` ran one read-only observation on macOS Console
**2025.1.7.9143: 1 passed in 4.73s**. Two public Gateway calls listed the
`PlaylistSlot` class fields and read the selected `PlaylistObject` detail.
Native metadata confirms class 5636096, `mustChildOf`, `notNull`, and reference
type labels `Container`, `Switch Container`, `Blend Container`, and `Sound`.
This establishes the exact metadata shape, not hierarchy semantics, mutation
effects or complete playlist support.

The existing sandbox lifecycle recorded no transactions, unchanged source file
hashes/mtime/tree metadata, clean process shutdown and sandbox deletion. The
final category record is line 289 of the local
`.waapi-skill-state/evidence/full-typed-input/macos-category-evidence.jsonl`.
The observation and original pytest log are under
`.waapi-skill-state/full-coverage/r62-playlist-metadata-7572b2d7-2025-r1/`.

Two focused public-Gateway fake-client controls passed in **0.38s**, including
rejection of a missing native flag. An earlier test collection skipped because
it imported the live-only module; the observer was separated from that fixture
before the passing run. No full Program/Non-live or Fresh gate ran. The 2023/2024
list-level variant and 2025 existing/new-slot implementation remain work under
#177/#178/#180. Historical branch inventories are not refreshed by this scoped
collection.

## 2026-10-21 R60 focused schema-seal follow-up

GitHub pure-code preflight on `99d8f115` reported **825 passed / 1 failed in
64.42s** (run `39549064298`). The sole failure was the non-object-set operation
schema aggregate. An isolated comparison with `7f457d01` established that only
the four 2022.1–2025.1 `object.setRTPC` contracts changed: owned ControlInput
construction, result bindings and their constraints. The other 145 contracts,
existing identity alternatives and required arguments remain unchanged.

The test now protects the new aggregate and retains all historical aggregates
using the four exact previous RTPC seals. An initial focused attempt exposed
the still-stale historical aggregate (1 failed in 0.42s); after preserving that
history explicitly, the same node passed in **0.40s**. No other local tests were
rerun. This test-only edit is absent from all R59 capture source maps; it grants
no new native, Fresh or broad-gate acceptance. The original CI failure remains
historical evidence.

## 2026-10-21 R59 Source completion and portable evidence integration

Candidate `4e3c2800` passed the **65-case program capture in 62.09s** after
repairing the Source selector binding and admitting the exact 26 Source branches
to the default product evidence policy. Five original version-specific Source
native attachments were reused without rerunning Wwise. The actual default
completion evaluator now verifies **91 branches: 65 metadata and 26 Source**.
The metadata policy requires native evidence for 60 branches and program evidence
for the five version-specific default-absence branches. Topic's 559 branches
still lack required native evidence; overall completion remains false.

The original import attempt exited unsuccessfully because its final assertion
read the inventory scaffold before applying evidence bindings. Its result is
preserved as failed. A separate read-only evaluation verified the completed
artifact effects, all **11,241 previous archive files** unchanged, and the same
651 binding identities. Official inventory generation/check and semantic
preservation review passed: 650 selected evidence rows changed, with obligation
identities, shapes, owners and unrelated rows preserved. The successor local
coordinator uses the actual completion evaluator; no import was replayed.

Post-import checks reported **4 passed / 1 failed in 318.35s**. The failure was
an obsolete test expectation that all 65 metadata branches required native
evidence. After aligning that oracle with the approved 60/5 policy, only the
failed node was rerun: **1 passed in 35.84s**. This test-only change leaves the
captured candidate identity unchanged. These are separate runs, not a single
five-test passing run.

No new native, Fresh Agent, Windows-host or full Program/Non-live gate ran in this
integration. The historical full Program failure is not superseded. Detailed
terminal receipts and the separate read-only verification are retained under
`/tmp/waapi-r59-integration/runtime-r5/run-4e3c2800-diagnosed-r5/`; original failed
attempts remain intact.

## 2026-10-21 R58 settled Source and evidence integration

Source/bridge candidate `35410b7e` passed **49 affected controls in 80.70s**
and one **60-case capture in 19.14s**. All four interface semantic seals and
existing generated interface artifacts matched; no interface refresh was needed.
One additive import and branch generation/check passed. Artifact candidate
`f5a6487e` then passed the two existing portable-product checks in **30.33s**,
with source/HEAD unchanged and no remaining owned process groups.

The import preserved all **2,683 earlier archive files** and added 1,096 files /
128,655,875 bytes. All 625 selected bindings and 272,313 native obligation
identities, shapes and owners remain intact. Only 624 Topic/metadata evidence
rows changed. Metadata remains 65 program facts / 60 historical native facts /
5 missing default-absence requirements; Topic remains 559 program facts with
559 native requirements missing. Original native candidates and current program
sources retain their separate attribution. Five scoped Source business rows do
not yet grant generated native credit; the #180 attachment reader remains work.

The native component results below belong to their frozen candidates. This
integration ran no Wwise, Fresh Agent, Windows native or broad regression gate.
The historical full Program failure is not superseded. Fixed preflight runs on
GitHub only. Detailed terminal receipts are retained under
`/tmp/waapi-r58-integration/run-settled-r1/`.

## 2026-10-21 R57/R58 scoped native Source copy and Save

The [Source fact ledger](../docs/plans/full-waapi-coverage/SOURCE_COPY.md) pins
original receipt hashes and separates raw diagnostic flags from Root's exact
effect assessment. The 2021.1 repeated two-property Synth graph on `6d4a3547`
passed one native node in 16.06s. Frozen `411e8173` then passed the modern existing
Synth/RTPC/ModulatorLfo/Curve node sequentially on Console 2022.1.19.8584,
2023.1.19.8928, 2024.1.13.9056 and 2025.1.7.9143 in 15.91/17.50/16.00/16.32s.
Each run had four separately authorized transactions, independent saved-file
and live-state oracles, unchanged sources and terminal cleanup. These are
component native results, not current-integration test runs. The Source fact
adapter remains required #180 implementation; no generated branch count,
constructor, other-class, Windows or Fresh acceptance is inferred.

## 2026-10-21 R55/R56 saved-copy, Tone and portable metadata integration

Accepted runtime/harness sources are Source saved-copy `ee78f00b` with explicit
Save-choice disclosure `4a6208a1`, full task consumers `20c8dcc8`, stationary
square `8d015764`, stationary triangle `4521245a`, and exact historical/current
metadata-source bridge `514c8100`. The current Program roster has **272 modules**;
that count is not a completed full gate.

The saved-copy protocol has scoped native evidence on Console 2021.1.14.8108:
one case at `cd272949` passed in **10.40s**, with separately authorized baseline
and final Save children, one copy, and an independent saved-XML oracle. It covers
the exercised Synth/RTPC/LFO/Curve graph with zero ObjectRefs. The original
collector category remains diagnostic; arbitrary graphs, ObjectRef remapping and
history are not certified. Full formal task-consumer program checks subsequently
exercise the actual Broker, grader, archiver and mandatory campaign reader,
substituting only the external Codex process and existing fake WAAPI boundary.
The final dirty-flow/classifier selection passed **2 in 19.44s**; read-only and
topology controls passed separately. Earlier component-only checks and mixed
failed attempts retain their original scope and verdicts. No Fresh run follows.

Stationary square/triangle checks preserve the requested cadence and gain under
their disclosed numerical tolerance. Triangle's final affected selections passed
**13 in 6.38s**, then **3 in 1.67s** after constant precomputation. These are
separate program selections, not a combined gate. The actual retained triangle
WAV is replayed byte-identically; its original diagnostic result is unchanged.
Missing phase witnesses remain partial, and envelope/noise/fractional and other
unverified Tone branches remain required. The exact metadata bridge passed
**19 in 41.07s**, including strict rejection of unknown or omitted source proofs.

Four sequential read-only native collections on frozen `860965d3` (2021–2024)
observed six fields providing ten exact empty-string/Boolean witnesses. Their
34 public calls and 82 native packets are retained in **262 sealed files /
1,607,698 bytes**. Source projects and cleanup checks passed. These observations
supplement the earlier R51/R54 originals; no default-absence claim is inferred.

Integration capture source `0377d16b` passed **60 selected cases in 20.47s**
(wrapper 21.12s), with no skips or source drift. Interface generation/check passed
in **16.591s / 16.839s**. The preceding `settled-r1` stopped before capture because
the reviewed new continuation command lacked its parser-policy seal; that failed
attempt remains preserved. Only the reviewed seal and derived inventory changed
before the fresh `settled-r2` capture.

Artifact commit `3f8f3146` preserves all **1,587 earlier archive files** and adds
1,096 files / 128,638,233 bytes through the existing importers. Thirty-five program
entries were refreshed; historical native attachments are exactly **9 R51 +
41 R54 + 10 R55**. Full original/current source maps and native bytes remain
separate: attribution is historical-native/current-program, not current-native.
Branch generation/check passed in **63.620s / 62.875s**. All 272,313 native
obligation identities, shapes and owners remain exact; only the selected 624
Topic/metadata evidence rows changed. Current accounting is **65 metadata program
passed, 60 live_metadata passed, 5 absent-default requirements missing**;
**559 Topic program passed, 559 native requirements missing**. Overall completion
remains false: 60 verified, 565 implemented_unverified, 271,572 unresolved and
116 approved exclusions.

On clean `3f8f3146`, the two actual portable-product checks passed **2 in 27.97s**
(wrapper 28.70s), with original context variables cleared, no local-evidence
fallback, independent program proof, unchanged source and empty owned process
groups. The fixed preflight is reserved for GitHub and was not repeated locally.
Exact commands, logs and preservation receipts are under
`/tmp/waapi-r55-integration/run-settled-r2`; captures remain under
`.waapi-skill-state/read-evidence-r55-settled-r2`. The earlier full Program result
remains FAIL (13,529 passed, 7 failed, 4 skipped). This integration is not full
Program/Non-live, Fresh, Windows or whole-ticket acceptance.

## 2026-10-21 R54 Source-copy, closed Save and five-version class metadata

Conflict-free merge `55865039` incorporates accepted class source `8a8d5f8e`,
including Source-copy `a8d30c5b` and Save `ae7e6e29`. Source-only copy now reports
its certified default-view fields/owner-frame scope explicitly; complete-copy
preservation stays false. Closed project Save is available on all five versions:
2021.1/2022.1 accept an empty business plan; 2023.1–2025.1 preserve optional
Boolean checkout choices and omission. Normal authorization/execute-once rules
and the `result_schema_checked` Save boundary remain intact.

The fixed Program roster now has **271 entries**: the three new worker modules
plus the actual portable product-attachment integration module. This is a roster
count, not a full Program run. Accepted worker-focused evidence remains bound
to its original source and was not repeated wholesale.

Interface generate/check passed once in **17.879s / 17.277s**, with unchanged
artifacts. The complete native class closure is **560/560 byte-identical** from
frozen `8a8d5f8e` to clean capture source `e860aed1`; the standalone integration
test and roster edits are outside that closure. One existing 38-node capture
then passed **38 in 7.56s** (wrapper 8.175s): five Topic cases, 30 metadata
cases and three R51-native/current-public replays. HEAD/all 2,763 tracked files
stayed exact. Fresh source closures contain 349 Topic / 344 metadata /
348 current replay files; the historical closure remains separately retained.
Current source identity is
`199e696ed430594a5c39b518082ee2e5bca2d9b812aa2f49facd0a0636325e9c`.

Root separately reviewed one sequential native class attempt per version on
frozen `8a8d5f8e`; all five passed with source/fixture/cleanup proof. Exact
builds are 2021.1.14.8108, 2022.1.19.8584, 2023.1.19.8928, 2024.1.13.9056 and
2025.1.7.9143. Sixteen actual field reads provide **41 exact leaf witnesses**,
by version **1 / 10 / 9 / 9 / 12**: Boolean true/false, null, number and empty
string alternatives as actually returned. All defaults were present; no absence
proof follows. The original five runs used 59 public Gateway calls and sealed
474 files / 2,646,283 bytes. Root's independent receipt is
`.waapi-skill-state/full-coverage/r54-root-class-native-review.json`.

Import `253ed73d` uses the existing portable importers and accepted class
attachment writer. All 838 earlier archive/projection files and non-replaced
index entries remain exact. Thirty-five fresh Topic/metadata entries and nine
fresh historical replay attachments replace only their selected predecessors;
41 class descriptors are additive. Each native original/seal is copied
byte-identically, with its native input and full original/current source proof;
program evidence remains independent. Additive storage is **749 files /
58,728,162 bytes**: Topic 25 / 37,704,043; metadata 150 / 5,397,147;
replay 33 / 11,443,951; class originals/attachments 541 / 4,183,021.

Branch generate/check passed once in **46.113s / 45.709s**. All 272,313 native
IDs/shapes/owners, 116 exclusions, requirements/native policy, interface bytes
and 79/91 source/index memberships remain exact. The 625 selected bindings
comprise 559 Topic + 65 metadata + one unchanged Move binding; only the 624
refreshed Topic/metadata rows change evidence/binding fields. Current accounting:
**559 Topic program passed / 559 native missing**; **65 metadata program
passed / 50 live_metadata passed / 15 missing**. The 50 retain nine historical
R51 witnesses separately from 41 current-native class witnesses. Remaining
alternatives stay assigned and required. Completion remains false:
50 verified, 575 implemented_unverified, 271,572 unresolved and 116 exclusions.

Generated candidate `25372579` passed one final **3-test focus in 16.43s**
(wrapper 17.158s): roster assertion, portable R51 originals and the actual
committed class product attachments. The actual product test blocked all
machine-local `.waapi-skill-state` reads, unset the original-root environment,
validated exact native/runtime source binding through the strict product reader
and independently required all 65 program facts. No skips; HEAD/all 3,512
tracked files stayed exact and every owned group exited. No synthetic class
positive substitutes for this actual archive check.

The earlier R53 production Source-only native diagnostic also remains bound to
`a8d30c5b`: one 2021.1.14.8108 attempt, **1 passed in 11.39s**, 67 public calls,
four separate transactions and 18 scoped runtime assertions. Its independent
saved-image oracle proves the genuine Synth fixture's serialized owned graph;
runtime full-copy authority/history remains open. Save reply validation alone
does not establish persistence, and ObjectRef remapping was not exercised.

Plans, exact commands, process/source/output and storage/preservation receipts
are in `/tmp/waapi-r54-integration/`; current captures are under
`.waapi-skill-state/read-evidence-r54/`. This merger launched no native, Fresh,
full Program/Non-live gate, local fixed preflight, install, push or PR edit.
Root owns publication and exact-head hosted CI; no main merge or ticket/family
completion is claimed. Original evidence and failed quarantines are retained.

## 2026-10-21 R52 saved-copy, Tone and exact metadata attachments

Runtime merge `191382e0` combines only accepted saved-copy `56a7c376`
(including `90c1089b`), Tone `7f3c360d` (including `005afc69` and `70f3ff0c`),
and metadata `5a5eeda4`, without conflicts. The shared destructive collector
combines both accepted additions; all other component files retain exact
accepted blobs. The Program roster adds `test_metadata_replay_attachments.py`
and its canonical required-entry/count assertion: 267 manifest entries.

Interface generate/check passed once in **18.174s / 17.963s**; generated
artifacts stayed byte-identical. Clean source `d1d9dd64` then received one
38-node capture: **38 passed in 7.86s** (wrapper 8.548s), comprising the existing
five public Topic and 30 metadata nodes plus three public replays of preserved
R51 metadata packets. HEAD/all 2,549 tracked files stayed unchanged. Full
closures remain 348 Topic / 343 metadata / 347 current replay files; the bridge
also retains all 343 historical sources. Source identity:
`32f90e32adca4c9cca68b7e831a3f0bba2ef9d93d4f08ffa1d5d84c1e6de8c76`.

Existing portable importers select 35 fresh entries with 140 byte-identical
originals and locator-only projections. The whole replay tree is copied
byte-identically, with nine additive sealed `live_metadata` attachments; original
program receipts remain unchanged. All 630 earlier archive/projection files and
non-replaced index entries remain exact. New storage is 25 Topic files /
37,625,197 bytes, 150 metadata files / 5,384,023 bytes, and 33 replay files /
11,439,167 bytes. No old archive or failed sandbox was deleted.

Branch generate/check passed once in **40.398s / 39.084s**. Strict current
accounting proves **559 Topic program passed / 559 native missing**, and
**65 metadata program passed / 9 live_metadata passed / 56 missing**. The nine
leaves are only original 2021.1.14.8108 Console RTPC reads: Color default 0
(five), ControlInput default null (two), OverrideColor default false (two).
Historical native execution and current injected public replay retain separate
identities; no current-native, mutation or other-host/version proof follows.
All 272,313 IDs/shapes/owners, 116 exclusions, requirements/native policy and
79/91 source/index memberships stay exact. Only 624 selected rows'
evidence/bindings change; complete=false, with 9 verified,
616 implemented_unverified and 271,572 unresolved obligations.

Generated `3973fb63` passed one focus: **9 passed in 12.11s** (wrapper 12.820s).
The portable-originals test actually ran with `WAAPI_R51_METADATA_ORIGINAL_ROOT`
absent and no skips, alongside exact Tone bridge acceptance/drift/partial-bridge
controls, compact 36-channel and large-marker terminal delivery, fixed manifest,
Topic selection and saved-copy protocol. HEAD/all 2,757 tracked files stayed
unchanged; all owned groups ended empty. Strict portable evaluation already ran
during branch generation/check; complete worker suites were not repeated.

Separately accepted native evidence stays bound to its original candidates.
Saved-copy `56a7c376` on 2021.1.14.8108 passed its one diagnostic node in
**11.07s**: four separately previewed transactions (baseline Save, empty Sound,
Source-only copy, final Save), 67 public calls and independent complete saved
subtree/live identity/owner/ShortID comparison. Save phases remain
`result_schema_checked`; create/copy phases are `verified`. The final collection
stays diagnostic-only, `business_effect_verified=false`. One genuine Synth
fixture exercises no ObjectRef remapping and proves no generic copy/history,
constructor or points-getter contract. Earlier native failures remain unchanged.

Tone `7f3c360d` on 2025.1.7.9143 passed its one diagnostic node in **9.39s**:
one 36-channel anonymous fifth-order-count sine/float32 envelope transaction,
12 public replies and one native Tone call. Its transaction is `verified`,
`business_state_verified=true`, under the declared artifact policy: exact
header/count/mask/frame facts and all 108 channel/segment observations, fixed
frequency/gain/linear envelope, independent phase per segment. Its original
collector category remains blocked/diagnostic, `business_effect_verified=false`,
without coverage credit. Phase continuity, internal channel-config type, other
waveforms, 2023/2024 native effects, other patches and Windows remain open.
Root's independent integrity review remains in
`.waapi-skill-state/full-coverage/r52-root-native-review.json`.

Plans, process/source/output receipts and preservation/storage proofs are in
`/tmp/waapi-r52-integration/`; captures are under
`.waapi-skill-state/read-evidence-r52/`. This integration ran no native, Fresh,
CLI Agent, install, full Program/Non-live, local fixed preflight, push or PR edit.
Root owns publication and exact-head hosted CI; no ticket/family closure or
main merge occurred.

## 2026-10-21 R50 exact created-Topic evidence and original-only diagnostic

Runtime merge `8bcd215f` combines only accepted Topic `8390ce8b` (including
`b1617894`) and original-only diagnostic `cbd067c2` from `17c0ffd3`, without
conflicts. All nine component files retain exact accepted blobs. The Program
manifest adds `test_created_topic_branch_evidence.py` with its canonical
required-entry assertion, for 266 manifest entries. No packaged runtime,
resources, guidance, public contract or interface seal changed; exact interface
artifact/policy proof justified skipping interface regeneration.

Clean combined source `470b9248` received one existing 35-node capture:
**35 passed in 6.88s** (wrapper 7.448s), comprising five actual public Topic
nodes and the 30 existing metadata nodes. Metadata recapture was required by
one actual changed whole-file seal, `branch_audit_completion.py`, and the
changed requirements identity. Its 343-file closure and the Topic's 348-file
closure remained exact; all 2,364 tracked files and HEAD stayed unchanged.

The reviewed importers selected five Topic and 30 metadata entries, copying
140 original JSON files byte-for-byte and changing only program locators in
35 projections. All 469 prior evidence files, including R26/R47/R49, remain
byte-identical. Topic artifacts occupy 37,625,113 bytes in 25 files; metadata
artifacts occupy 5,383,723 bytes in 150 files (43,008,836 bytes total). These
immutable archives were retained without format redesign or another capture.

Branch generate/check each passed once after capture/import, in
**37.722s / 37.078s**. Existing strict evaluation proves **559 exact Console
object.created primitive publish leaves program passed / 559 native missing**
(79/112/116/116/136 across 2021–2025) and **65 metadata program passed / 65
live_metadata missing**. Injected callbacks establish no native emission,
applicability, include/omission, co-occurrence or lifecycle behavior. All other
4,343 created-Topic rows stay unproven. All 272,313 obligation IDs, shapes and
owners, original R26, all 116 exclusions and 79/91 source/index memberships
remain exact. Only the selected 624 rows' evidence/requirements/bindings change;
complete=false, with 625 implemented_unverified and 271,572 unresolved.
Current source identity is
`e2c47fbef9e63023f219039924e86a59350e8a6d94b2cc3d933d639f147b0673`.

On generated candidate `987fe1c2`, one deduplicated focus passed **5 tests in
4.08s** (wrapper 4.702s): fixed manifest, exact Topic selection, existing metadata
public-leaf compatibility, diagnostic first-hop failure/no-write/no-fallback,
and the existing copy category's actual v3 validator. Strict current portable
evaluation was already performed by branch generation/check and was not
repeated by another broad pytest evaluation. All 2,539 tracked files and HEAD
stayed unchanged; every owned process group ended empty. Original plans,
process/source/output receipts, import/storage and preservation proofs are in
`/tmp/waapi-r50-integration/`; fresh ignored capture roots are under
`.waapi-skill-state/read-evidence-r50/`.

The separately completed native root
`r50-original-owned-read-cbd067c2-2021-r1` remains its original **FAIL, 5.98s**
(wrapper 6.591s): the first bounded Source `@RTPC` query failed natively with
`ak.wwise.query.invalid_query`, `Unknown property RTPC (61)`. Eight public calls,
31 native archives, zero writes/transactions; all 18 Source fields were observed,
but RTPC membership, ControlInput/LFO, Curve fields/points and copied graph
were not reached. Source hash/size/mtime/tree and candidate stayed unchanged,
owned processes ended, and the failed sandbox remains quarantined. This exact
rejection proves neither native absence nor complete Source-copy semantics;
no historical receipt or failed verdict was rewritten or regraded.

No native, Fresh, CLI Agent, install, full Program/Non-live, local fixed
preflight, push or PR edit ran in this integration. Root owns publication and
exact-head hosted CI. Final implementation/evidence obligations remain open;
no main merge or ticket closure occurred.

## 2026-10-21 R49 transfer admission and exact metadata-default evidence

Runtime merge `c7b21ae9` integrates only frozen `4199c5d1`, `2c444f69`,
`8e2eb229` and `0a183133` from `4ccbd66e`, without conflicts. The shared
collector composes both accepted additions; the other component files retain
exact accepted blobs apart from the two intentional Program-manifest edits.
Copy/move admits resolved compatible custom WorkUnits and Source-to-Sound
transfers with required actual source type, exact class/category checks and
execution/verification drift checks. Transfer admission does not prove complete
Source/plugin copying or constructor support. The ordinary Source recorder now
preserves complete original query replies. The legacy diagnostic supplies the
category field required by the existing finalizer; original failures stay frozen.

After interface generation/check, clean source `e7ec62de` received one existing
30-node metadata capture: **30 passed in 5.83s** (wrapper 6.435s). All 343
source seals and 2,210 tracked files stayed unchanged, with no owned process
remaining. Thirty new portable entries retain byte-identical originals and only
relocate the program locator in projections. All 319 pre-existing evidence fixture files,
including R26 and R47 r1/r2, remain byte-identical; the bundle README updates
only its current-index description. The fixed Program manifest
now includes the metadata-default test file and contains 265 entries; this is a
manifest count, not a passing-test count.

On generated candidate `16ead09b`, one deduplicated focus passed **11 tests in
27.27s** (wrapper 27.864s): complete ordinary-Source query/all-call immutability,
actual legacy category validation, current portable metadata evaluation, the
canonical manifest, positive/missing source-type copy/move, two source
class/category drift controls and one complete Source-copy flow. HEAD and all
2,360 tracked files stayed unchanged; the owned process group ended empty.
Worker checks remain separate original receipts, not an aggregate gate.

Interface generate/check passed once in **17.455s / 17.627s**; branch
generate/check passed once in **25.247s / 23.370s**, after the frozen capture
and import. Only ten copy/move safety disclosure contract references and their
reviewed aggregate seal refresh; all 153 machine contracts, parser/continuation
contracts and 79/91 source/index memberships remain exact. All 272,313 native
IDs, shapes and owners remain exact. Only the selected 65 default-result rows
acquire program evidence: **65 program passed / 65 live_metadata missing**,
all implemented_unverified. Original R26 and all 116 exclusions are unchanged;
complete=false (66 implemented_unverified / 272,131 unresolved). Source identity
is `6a83b79f8b61ffae5ddfd8297f0c1c7d93914d8c39da975a23114b4cd91d1127`.
Original commands, process/source/output seals and proofs are retained under
`/tmp/waapi-r49-integration/`; capture is in ignored
`.waapi-skill-state/read-evidence-r49/capture-r1/`.

Separately completed historical macOS Console evidence remains bound to its
original candidate and root under `.waapi-skill-state/full-coverage/`:

- `r46-render-history-4ccbd66e-2025-r1`: **PASS, 16.51s**, 227 calls / 2,821,903
  receipt bytes, seven verified transactions and exact source/undo/redo state.
  Hosted CI run `39456571914` passed exact `4ccbd66e`; neither is R49 evidence.
- `r47-ordinary-source-da0becf6-2025-r1`: original **PASS, 12.50s**, 66 calls,
  three verified transactions and retained file/Tone state. Its root-review
  addendum records in-place query-payload mutation, so those query replies are
  not exact original Gateway receipt proof. `2c444f69` repairs copying with
  program evidence only; no new native acceptance is claimed.
- `r48-legacy-copy-ae7a6b4b-2021-r1`: native Source-only copy admission and 18
  observed scalars succeeded, with 55 calls and two verified transactions, but
  the overall result remains **ERROR_EVIDENCE_FINALIZATION** (one body passed,
  one teardown error, 12.78s) because the category field was missing. Original
  failure, source closure and quarantine remain; `8e2eb229` is program-only.
  Copied owned-object remapping/full-copy semantics remain unproved.

This integration ran no local fixed preflight, full Program/Non-live, native,
Fresh, CLI Agent, installation, other-host validation or publication. Root owns
review, push and exact-head hosted CI. Remaining implementation/evidence and
final gates stay open; no main merge or ticket closure occurred.

## 2026-10-21 R46 existing Source preservation and Render collector integration

Runtime merge `5e41bed1` combines only accepted `7979072d` and `dceb20f1`
from workflow-only `06fcadaf`. All 11 component files retain their exact pinned
blobs; the merge had no conflicts. Ordinary existing Sound/Voice Source
placement now retains observed plugin/file Source state through bounded field
pages. The scoped Render collector keeps complete calls and independent state
while replacing duplicate phase payloads with exact call/hash references.

One combined focus through pinned Poetry and `ci/test.sh --mode nonlive` passed
**9 tests in 27.44s** (wrapper 28.409s): three file Source preservation cases,
two paged-field cases, two stripped-origin controls, the staged two-Preview
flow, and one modern Render path with captured native metadata and receipt
sizing. HEAD and all 1,905 tracked files stayed unchanged; no owned process
remained. Original argv/source/process/output seals and logs are retained under
`/tmp/waapi-r46-integration/`.

Interface generate/check and branch generate/check each passed once, serially:
**18.067s / 17.547s / 24.689s / 23.734s**. Only the reviewed operation-contract
aggregate seal and four `object.set` public contract references refresh. All 153
machine schemas, parser/continuation contracts, 79/91 source/index memberships,
272,313 native obligations and compressed bytes, owners and evidence requirements
remain exact.

Original `027ac095` native results remain separate: 2022 **PASS** and 2025
**FAIL** at the unchanged 8MiB receipt ceiling. The latter verified source and
undo, then stopped with redo awaiting confirmation; redo was not executed.
`r45-render-history-027ac095-native-summary.json` under Root's ignored
full-coverage directory retains both attempts and their original receipt hashes.
The collector repair and simulated sizing grant no native redo acceptance.
No local preflight, full Program/Non-live, native or Fresh run occurred in this
integration. Root owns exact-head hosted CI after publication and a separately
scheduled new 2025 Render sandbox case. Broader Source/history work and final
gates remain open; no ticket is closed.

## 2026-10-20 R44 scoped Source, staged completion and exact Render/history integration

Runtime merge `f173d0c0` combines only accepted `4f869927`, `d8c55b4d` and
`39b7cfc9` (including exact-history `cb0e6b3d`). Withdrawn existing-GUID
autosuffix branches are excluded. The 23 component files retain exact blobs,
clean shared-file composition or the reviewed additive test-helper resolution.

The frozen merged tree, with reconciled/generated artifacts, completed these
checks through the pinned Poetry interpreter and existing test driver:

| Check | Result | Scope |
| --- | --- | --- |
| Central `ci/preflight.py` | **826 passed, 51.09s** | Complete fake public-route matrix, roster/schema seals and Tone terminal controls |
| Shared-conflict focus | **7 passed, 25.30s** | Staged completion/drift, exact-history positive/two faults, retained atomic-2025 and explicit-current-2022 prewrite boundaries |

Both test runs kept all 1,902 tracked files and HEAD unchanged and left no owned
process. Original argv, source/process/output seals and logs are retained under
`/tmp/waapi-r44-integration/`. Interface generate/check and branch generate/check
each ran once, in that order: **17.398s / 17.595s / 25.239s / 40.039s**.
Only three reviewed aggregate source seals refresh. All 149 machine-contract
rows outside the four affected `object.set` versions remain exact. The 79/91
source/index memberships, all 272,313 native obligations and compressed bytes,
requirements, ownership and evidence policy remain intact.

Separate original 2025 macOS Console receipts remain bound to their component
candidates: `d8c55b4d` staged Voice/Source **1 passed, 8.05s** (34 calls, two
separately verified `object.set` transactions), and `cb0e6b3d` exact graph
rename/notes/history **1 passed, 19.14s** (114 calls, five verified transactions).
Their roots are `r44-gateway-staged-source-d8c55b4d-2025-r1` and
`r43-history-exact-cb0e6b3d-2025-r1` under Root's ignored full-coverage directory;
neither was rerun or promoted to integrated native acceptance. Render native
acceptance, broader Source/Render/history work and final full Program/Non-live
gates remain open. No new native, Fresh, hosted-CI or Windows run was performed
by this integration, and no ticket is closed.

## 2026-10-20 R42 scoped Source selection and staged Voice integration

Runtime merge `779823d3` combines accepted `8664cfb6`, `1a1b3b03` and
`bba85da9` from `e80d9250`. The separate #192 suffix/history candidate is
excluded. These original results are separate receipts, not a combined gate:

| Candidate and lane | Original result | Scope |
| --- | --- | --- |
| `e80d9250`, full Program | **13,529 passed / 7 failed / 4 skipped, 5,044.89s** | Retained failed gate; no regrading |
| `6f25cfd0`, seven selected repairs | **7 passed, 8.74s** | Only the original failed nodes |
| `8664cfb6`, RTPC portability follow-up | **3 passed, 2.37s** | Windows-shaped continuation on macOS; no Windows host credit |
| `d64e0db7`, 2025 Console Source-plugin selection | **1 passed, 8.58s** | 70 calls, four previewed transactions, 170 native archives; current-view A→B plus preservation |
| `1a1b3b03`, 2025 Console staged Voice/Source | **1 passed, 6.10s** | Diagnostic-only; 33 calls, two transactions, 86 archives; atomic language unresolved |

Exact native roots are `r42-source-selection-d64e0db7-2025-r2` and
`r41-planned-source-staged-1a1b3b03-2025-r1` under Root's
`.waapi-skill-state/full-coverage/`. The three original atomic Source r1/r2/r3
failures remain FAIL with quarantined sandboxes. Source-plugin r1 stopped at a
prerequisite before host launch and remains separate. Passing native runs kept
source full hash/mtime/tree unchanged, left no owned process, and deleted only
the passing sandbox. No family, other-version, native Windows or Fresh credit
is inferred. Selected program chronology remains in
`/tmp/waapi-r42-seven-program-repairs/handoff.md`.

Four serial interface/branch generate/check commands passed once in
**16.605s / 16.775s / 23.544s / 22.241s**. All 153 Registry machine seals and
272,313 native obligation rows, including their compressed bytes, are exact.
Only reviewed public disclosure references, the one operation aggregate seal,
source/hash/line/candidate data and four exact requirement rows change.
#195 adds requirements only, preserving program+native policy and historical
entries; there is no capture/index entry or new PASS. Source membership remains
79/91 indexed entries and full candidate closure 330 files. No merger pytest,
native, Fresh or new final-candidate gate ran; Root owns promotion and validation.

## 2026-10-20 R41 scoped Source, active-selection and reimport integration

Runtime merge `edbc24cb` combines accepted `aaa91777`, `8ec0925d` and `01a65041`
from `e80d9250`. Seventeen component files retain their exact blobs or clean
shared-file composition. The following are separate original focused receipts;
none is a combined final-candidate or full Program result.

- Source construction: **29 passed in 10.06s**, then only collision/retained-GUID
  controls **2 passed in 1.07s**. The real Voice→planned Bus unknown-language
  continuation tracer went **1 failed in 0.68s → 1 passed in 0.64s**. Earlier
  plain-Source attempts were test-design failures and remain recorded as such.
  Collector prior-owner extra-child RED was **1 failed in 3.69s**; changed
  happy/fault controls were **2 passed in 6.03s**, proving the 74-call collector,
  three distinct executions, exact native-byte archive and retained child sets.
- Query: the new predicate tracer went **1 failed in 0.39s → 1 passed in 0.40s**;
  relationship/mixed producers **2 passed in 0.42s**, existing affected guards
  **22 passed in 1.21s**. Only the full 1000-owner control went **1 failed in
  0.51s → 1 passed in 0.64s**; structured config-drift/context controls went
  **2 failed in 1.27s → 2 passed in 1.30s**; child/caller-bound guards were
  **2 passed in 0.37s**. Setter linkage disclosure and public Preview summary
  have separate passing receipts; neither promises unlinking or isolation.
- Reimport: inactive-filename public RED was **1 failed in 0.62s**, then
  **1 passed in 0.51s**. Distinct public effect/boundary controls were **9 passed
  in 2.41s**, unchanged 2021 guards **29 passed in 1.54s**, and affected public/
  later-version controls **12 passed in 1.43s**. Contradictory exact Source-path
  RED/GREEN was **1 failed in 0.66s → 1 passed in 0.71s**. Empty-Sound Source
  insertion exposed a further prewrite gap (**1 failed / 1 passed in 0.93s**);
  the same two controls passed in **0.98s** after binding the empty precondition.

Full chronology and original argv/outcomes remain in
`/tmp/waapi-r41-planned-source/handoff.md`,
`/tmp/waapi-r41-multi-sound-query-handoff.md`,
`/tmp/waapi-r41-owner-bound-error-context-handoff.md` and
`/tmp/waapi-r41-reimport-active-source-handoff.md`. Focused tests used pinned
Poetry via `ci/test.sh --mode nonlive`; no counts are summed across stages.

Four serial interface/branch generate/check commands passed once in
**17.637s / 17.855s / 24.686s / 23.505s**. Restoring original policy formatting
with the same two hash values invalidated its raw-byte branch source seal; only
the branch generate/check pair repeated, passing in **24.666s / 23.455s**. The
first receipts are retained and the interface pair was not repeated. All 153
Registry machine seals and 272,313 compressed native obligations, ownership,
statuses and evidence remain exact.
Two reviewed aggregate disclosure seals, four Source business contracts, four
setter linkage contract references and source/hash/line/candidate data refresh;
there is no new branch credit. 2025 fixture LFS objects were materialized from
local storage only (15 objects, zero remaining pointers; no fetch).

Native originals are unchanged: the 2022 platform diagnostic r2 is **FAIL in
11.84s** (only Linked final saved selection, no divergent-platform proof), and
2024 owned OS observation is **BLOCKED / 1 skipped in 224.27s** (exact window
observed, one click without image change, no saved-value proof). Both retained
sandboxes/evidence and unchanged source/zero-owned-process results remain.
Root's full Program on `e80d9250` is still pending at this stage; its eventual
result must be recorded separately. No merger pytest/native/Fresh run occurred.
The next reviewed 2025 Source construction run is Root-owned and not yet claimed.

## 2026-10-20 R40 scoped regression, Voice context and stationary Tone

Runtime merge `495f8a7f` preserves accepted graph `026f9181`, Voice `89d0ef9f`
and Tone `49e4b69e` components: nine exact file blobs, without merger fixups.
Root's original R39 failed-node subset on `6e126276` ended **456 passed,
10 failed, 2,008 deselected in 103.95s**. Its retained original log is
`.waapi-skill-state/full-coverage/r39-failed-subset-6e126276-r1/run.log`.
This is a failed subset result, distinct from both the R38 subset and the
earlier full Program failure; R40 does not replace it with an aggregate PASS.

The ten graph residuals have separate staged results: **5 passed / 5 failed in
1.26s**, only five unresolved cases **1 passed / 4 failed in 0.73s**, then only
four remaining cases **4 passed in 0.58s**. Existing 7/8 KB compactness limits
remain unchanged; full public inspection retains the complete RTPC declaration
and batch precondition. No final ten-node or broad rerun is inferred.

Voice controls include **19 passed / 4 failed in 4.81s**, corrected four controls
**4 passed in 1.24s**, final two original-language negatives **2 passed in 0.32s**,
and the unrelated Source-preservation RED **1 failed in 0.76s** followed by
**1 passed in 0.65s**. These are separate receipts, not a combined result.
The new empty Voice language is validated construction context in 2022.1–2025.1,
not a persisted Sound language or localized Source. Existing-merge language
effects and atomic planned-parent Source construction remain #179/#180/#181
work. Staged Voice creation then Source-plugin creation on its bound existing
GUID already exists; the atomic gap does not mean all Source creation is absent.

Tone's public wrong-frequency RED is **1 failed in 0.93s**. Separate successor
selections passed **13 tests in 6.18s** (retained-file route combinations),
**16 in 7.79s** (signal/partial controls), **45 in 19.85s** (existing guards),
and **11 in 12.76s** (short-record/diagnostic controls). Overlapping selections
are not summed. Exact original failures, projection corrections and argv are in
`/tmp/waapi-r40-tone-handoff.md`; graph and Voice chronology are in
`/tmp/waapi-r40-graph-residuals-handoff.md` and
`/tmp/waapi-r40-voice-language/handoff.md`.

Stationary zero-attack/release sine verification checks frozen frequency/gain
within a disclosed numerical policy, including every active sample and exact
masked-off silence. Retained native bytes are reused offline; original native
outcomes remain unchanged. No new native/Fresh run or business acceptance is
claimed. Other waveforms/envelopes and remaining #193 scope stay required.

Four serial inventory generate/check commands passed once. Only the four
2022–2025 object.set `sound_semantics.language_and_media` disclosure leaves,
their public contract references and reviewed aggregate seal change, alongside
source/hash/line/candidate refreshes. All 153 Registry machine seals (including
the `6085...` object.set literal), source membership and 272,313 native obligation
bytes/statuses/ownership/evidence remain unchanged. No merger pytest ran; Root
owns publication and selection of the next settled gate.

## 2026-10-20 R39 scoped regression integration

Frozen runtime merge `c51371d1` preserves accepted graph fixtures `3eb19047`,
registry fixtures `373b9ff4`, optional active-source diagnostic `34a64ac1` and
Render/remaining fixtures `4404f41d`: all 21 component files match their reviewed
blobs. The Render repair retains explicit reference intent, binds planned
targets to the existing graph GUID proof and rechecks certified equivalent
platform views. Public schemas and seals for all 153 versioned operation rows
(34 named operations) remain equal to `695344f1`.

Root's original **R38 failed-node subset** on exact `695344f1` ended **976 passed,
466 failed, 3,598 deselected in 375.99s**, exit 1 (wrapper 376.777s). Its 1,897
tracked files stayed unchanged and no owned process remained. Original records
remain in `.waapi-skill-state/full-coverage/r38-failed-subset-695344f1-r1/`.
This differs from the earlier full Program failure on `c18225d9` recorded below;
neither is an R39 acceptance result.

R39 controls are separate staged Non-live runs, not an aggregate gate:

| Component selection | Original result |
|---|---|
| Four graph fixture files and related controls | 106 passed in 30.52s |
| Registry original failed nodes and related controls | 126 passed, 35 failed in 10.29s |
| Only corrected registry residuals plus retained Japanese-language boundary | 31 passed, 5 failed in 0.64s |
| Only five remaining registry corrections | 5 passed in 0.28s |
| Only registry cleanup-affected data controls | 10 passed in 0.39s |
| Render certified-equivalent-view positives and prewrite drift controls | 4 passed in 4.23s |
| Other modern Render version controls | 5 passed in 5.29s |
| Only final compound directory-entry assertion correction | 1 passed in 0.97s |

The remaining component's original 75-node closure maps to its staged receipts;
it is not a final-candidate 75-test run or a sum of passes. Original intermediate
failures, including a registry collection error before any test ran, remain.
Exact selections and receipts are indexed in `/tmp/waapi-r39-graph-fixtures-handoff.md`,
`/tmp/waapi-r39-registry-fixtures-plan.md` and
`/tmp/waapi-r39-other-fixtures/handoff.md`. The original no-media Japanese merge
request remains an exact unresolved-boundary control under #180/#181; its
separate positive proves platform scoping only.

Four serial inventory generation/check commands exited zero once. Only the
registry source hash, three existing source-index entries and native candidate
identity refresh; interface inventory, source membership, native descriptors and
all 272,313 compressed obligation rows remain exact. No merger pytest, native,
Fresh or replacement broad gate ran at that handoff. Root owned the subsequent
466-node subset; its original result is recorded in the R40 entry above.

The separate Root-owned 2021.1 diagnostic on `34a64ac1` **failed in 12.78s** at
`ordering_counterexample_unproven`. All three two-source copies' path joins
matched saved ActiveSource GUIDs, but the active source was always ordinal zero
in public and saved ordering. This remains blocked/diagnostic-only with no
generic active-source credit. Root's method review supports a future narrow
2021 file-backed path join with program order-permutation and ambiguity
controls, without another native boot solely to change the active ordinal.
No resolver is implemented yet; plugin/no-file, equal-path, unlinked-view and
active-choice-transition cases remain #181 work. See the retained native
follow-up.

## 2026-10-20 R38 selected regression repairs

Runtime merge `5fcd2d97` preserves accepted components `8836b0e5` (local-import
binding), `2c2ef80b` (version-bound import class fixtures), `7ad1f0f5`
(condition class fixtures) and `122ea303` (compact directory prose, structured
error context and assigned fixtures) without merger fixups. Production class,
drift, readback, continuation and output-bound safeguards remain intact.

These are separate staged Non-live selections through the pinned Poetry
`WAAPI_TEST_PYTHON` and `ci/test.sh`; no aggregate gate result is inferred:

| Component selection | Original result |
|---|---|
| Replacement copy/move across five versions and optional notice | 11 passed in 5.73s |
| Import tracers, version-spanning positives and malformed/drift/alias controls | 39 passed in 2.54s |
| Condition fixtures, first selection | 91 passed in 37.63s |
| Condition fixtures, remaining roles and three new corruption controls | 67 passed, 3 failed in 21.76s |
| Only three new corruption controls, first assertion correction | 3 failed in 1.03s |
| Same three controls, exact wrapper/inner assertions corrected | 3 passed in 0.96s |
| Gateway/small regressions and related controls | 23 passed, 1 failed in 26.02s |
| Only remaining policy-create fixture, type/class corrected | 1 passed in 0.97s |

The condition failures were test-author expectations: the strict product
returned `OPERATION_DRAFT_CHECK_FAILED` with `INVALID_READBACK` for
missing/malformed class and `INVALID_TARGET_TYPE` for mismatch. The small
selection's residual failure exposed stale fake PropertyContainer state for a
declared ActorMixer. Neither correction relaxed production behavior. The
2021.1 generic active-source boundary remains an open #181 implementation gap.
Original component logs/argv/process receipts remain at the paths in
`/tmp/waapi-r38-replace-fix-handoff.md`,
`/tmp/waapi-r38-import-fixtures/handoff.md`,
`/tmp/waapi-r38-class-fixtures-handoff.md` and
`/tmp/waapi-r38-small-regression-triage.md`.

On frozen `5fcd2d97`, four serial inventory generation/check commands exited
zero once. All four policy seals, 79 source members, 91 source-index members,
272,313 native obligation rows and compressed artifact bytes remain exact;
only existing source hashes/line offsets and native candidate identity refresh.
No merger pytest, full Program, native or Fresh run occurred. At that checkpoint
the original 1,442 failed-node subset had not yet been retested; the subsequent
exact `695344f1` subset result is recorded above. The earlier full-gate failure
below remains unchanged and no broad PASS credit follows.

## 2026-10-20 R37 focused integration and original Program failure

R37 `510a40f5` merges accepted history `4a8fee72` and portable evidence
`b9633fad` without component edits. Four serial inventory generation/check
commands exited zero once; no pytest, native or Fresh run was added for the
merge. All 272,313 obligation IDs and 116 exclusions remain. The sole changed
R26 move-single result row is `implemented_unverified`, with both required
program/native outcomes `missing` (reason `'artifact'`); the historical program
candidate has no equivalence attachment. No historical PASS becomes current
proof. All other obligation rows remain exact.

History evidence remains staged: parent-proof/discovery controls passed
**11 tests in 10.55s**; the later external-reference-only regression failed,
then passed **1 test in 2.76s** after its activation repair. These public
fake-native controls cover exact-intent ancestor/phase/history behavior across
the supported lanes; native-chosen suffixes, cross-child Render preservation
and native acceptance remain open. The portable default CLI control passed
**1 test in 80.42s**, its four integrity controls passed **4 tests in 79.70s**,
and the explicit missing-policy regression failed in **20.07s**, then passed
**1 test in 26.90s**. No staged results are summed into an R37 gate.

The separate original fixed Program run on exact `c18225d98ecc9f5be91da559a6f728042bec8b65`
ended **1,442 failed, 12,000 passed, 4 skipped in 4,891.23s**, exit 1
(wrapper 4,893.158s). Source snapshots and all 1,891 tracked files are unchanged;
the owned process group is empty. Original `result.json`, `run.log`, process
and before/after receipts remain under the Root checkout's
`.waapi-skill-state/full-coverage/program-r36-c18225d9-r1/`.
The log SHA-256 is `4d70acd3c944d7dfcd351b9530f93ed410601c7a573f8a5dd970485df6c2e309`.
This is a failed earlier-candidate broad gate, not an R37 result. Failure triage
and replacement broad acceptance remain open; passing individual cases grant
no gate PASS credit.

## 2026-10-19 Tone writer compatibility and bounded operator observation

Integration `af637e20` preserves the two accepted component filesets without
merge edits; four serial inventory commands passed, changing only the native
candidate hash. Tone regression evidence remains staged: four original-byte
controls passed after their genuine failures; eight format/older-lane controls,
two new matching-catalog controls and five compatibility controls passed in
separate scoped runs. No aggregate full-gate result is inferred.

On fixed `1e07d63f`, matching Console 2023/2024 collection passed **1 test in
11.07s** and **1 test in 9.95s**, respectively. Both final lifecycle rows pass;
source full hash/mtime/tree and 1,891 tracked files are unchanged, sandboxes are
deleted and owned processes ended. All eight native WAVs match corresponding
original 2025 files. Each has a separate transaction with successful structural
verification and explicit `partial_tone_artifact`; active signal acceptance is
unfinished. The original four 2025 failed verifications remain unchanged.

The developer operator gate passed **2 focused controls in 8.88s**. Its owned
2024 attempt on `6570e7c2` is final **BLOCKED** (**1 skipped in 58.79s**): the
computer-use inventory could not identify the isolated Wine app. No GUI action
occurred; source hash/mtime and 1,886 tracked files stayed unchanged, processes
ended and the sandbox/evidence are retained. Pre/post Inspect global scalars
remain 1/1000 and do not prove saved-session values. No further GUI attempt,
Fresh, Windows acceptance or whole-ticket closure is claimed.

## 2026-10-19 ordinary hierarchy history and native diagnostic evidence

Integration `3f7205e1` preserves accepted graph `4469adba`, frontend `ae95b5cc`
and Tone collector `205097b6` source files without merge edits. Four serial
inventory generation/check commands passed once. The only semantic contract
change is five-version undoGroup hierarchy scope and its still-open ancestor
rename dependency. Native obligation identities, requirements and evidence are
unchanged. No aggregate pytest rerun or broad gate was added for this merge.

Graph evidence remains staged: `4926f900` passed **7 tests in 8.83s** covering
five-version internal-reference source/history behavior and two compound graph
flows; `70023040` passed **4 tests in 4.03s** for the later aggregate Render bound.
Root's same-basename case exposed a real rejection; `4469adba` then passed that
case and its existing reference control (**2 passed in 2.99s**). These establish
program behavior, not native graph-history acceptance or whole-ticket closure.

The owned 2024 Authoring diagnostic on `ae95b5cc` passed **1 test in 44.34s**;
source hash/mtime and 1,886 tracked files were unchanged, its sandbox was deleted
and owned processes ended. Root's independent archived-image review confirms
Minigun session loading in an ObjectTab, selected GUID and Materials=Concrete.
Filtered RTPC/other saved values remain unverified. The category intentionally
stays diagnostic/blocked. Earlier `493b0d35` cleanup BLOCKED, `c8238eba` two-view
FAIL (**48.44s**) and `57ab9859` missing-view FAIL (**37.46s**) remain original
results; absence of a separately named view did not prove failed activation.

The owned 2025.1.7.9143 Console characterization on `205097b6` passed **1 test
in 10.74s**, retaining four original mono sine WAVs (int16/float32, 0/-6 dB),
39 public calls, independent transactions and complete raw evidence. Source
hash/mtime/tree and 1,886 tracked files were unchanged; cleanup completed.
All four transaction verifications remain **verification_failed** because the
Tone parser rejected the actual zero-valid-bits extensible headers. Collection
success grants no waveform/level acceptance; the diagnostic category is blocked.
No Fresh or Windows acceptance is added. Full gates and final review remain open.

## 2026-10-19 TSV admission and Soundcaster diagnostic follow-up

Integration `dacfa842` preserves component evidence without redundant reruns.
The original 2022 TSV regression first failed because `draft-check` accepted
`IsVoice`; its repaired control passed **1 test in 0.69s**. At `6ed4f2e4`,
the alias rejection and valid Sound SFX import passed **2 tests in 0.81s**.
These are separate staged results. The conflict-free merge preserves each
accepted source file; four serial inventory generation/check commands passed,
with unchanged schema seals, Program roster and native obligations.

Diagnostic component `72021d16` passed **2 focused tests in 4.60s**. The real
2024 Authoring attempt on `493b0d35` has a **BLOCKED final outcome**: the test
body passed in **54.13s**, but the post-teardown port check failed. Source full
hash/mtime and all 1,886 tracked files stayed unchanged; no owned process
remained. A later independent bind found the port free without regrading the
original attempt. Both archived PNGs were identical main-editor images; Root
review found no Soundcaster session or values. No preservation credit is given.
The original sandbox, receipts and images remain retained. No Fresh or broad
regression was added; final gates and remaining native validation stay open.

## 2026-10-19 actual class and compound history integration

Fixed `a047bf0d` passed **5 selected tests in 7.71s**: the cross-platform
Program roster, the 2022 null-constructor/history compatibility case, compound
created-field history on 2022/2025, and compound object.set Render plus notes.
All 1,886 tracked files and HEAD remained unchanged; the owned process group
was empty. Four serial inventory generation/check commands exited zero.
The actual Program roster is 263 unique entries after adding the public generic
class controls. All 272,313 native obligation identities, semantics, requirements
and historical evidence remain unchanged.

Component evidence remains separate: `90d7a483` passed only the four new
2021–2024 ordinary class parameters (4 passed, 1.22s), retaining the earlier
2025 result without rerunning it. Compound successor `92e816bc` passed five
typed child-ownership controls and three compatibility checks in separate
runs. These are program results, not native acceptance or a combined full-suite
pass. No local preflight, broad gate, Wwise or Fresh run was added for this
integration; final Program/Non-live and native acceptance remain outstanding.

## 2026-10-18 object-dump and immutable history-page integration

Fixed `841ae9b2` passed **3 selected tests in 2.98s**: large external dump
validation with a compact reply, lossless long-notes history pages, and the
existing immutable None-state page/cursor contract. All 1,885 tracked files and
HEAD remained unchanged; the owned process group was empty. Four serial
inventory generation/check commands exited zero. A separate wrapper bookkeeping
assertion stopped after the second generator because it incorrectly required
changed source hashes to remain equal; its original failure was retained, the
exact source changes were reviewed, and only the remaining checks ran.

No local preflight, full Program/Non-live or native rerun was added. The original
`bfd411ac` 2024 dump test remains **1 failed in 9.57s**. Fixed `4dcf1a6f` then
parsed its exact retained 3,638,677-byte artifact offline: 134,036 nodes, depth
three, original hash unchanged. This proves the parser repair only. Session
preservation, compound history and generic class completion remain separate
work. The prior completed gate results retain their original candidates.

## 2026-10-18 constructor repair and Authoring startup follow-ups

Final integration `59b270b1` passed **6 selected cross-path tests in 12.22s**:
2021 legacy import, 2022 null creation, multi-field history, modern and legacy
Render history, and raw-metadata drift rejection. The run preserved all 1,885
tracked files and left no owned process. Serial generators/checks passed with
unchanged native obligation/ownership/requirement/evidence bytes and Program
roster 262. No local 825-test preflight, full Program/Non-live or new native
campaign was run for this integration; original component evidence below stays
bound to its original candidate.

Later focused native successors completed separately: `a3b70b45` passed the
2021 legacy import collector (**1 passed, 17.16s**); `3b8f88ba` passed the
2024 Authoring startup/metadata diagnostic with child-only automation mode
(**1 passed, 47.68s**). Both preserved source full hash/mtime and 1,883 tracked
files, deleted their passing sandboxes and left no owned process. The import
case also preserved source tree metadata. The first proves the original three
import effects with a complete unique-source-child oracle, not generic 2021
active-source selection; the second proves startup and metadata observation,
not Authoring mutation or full media-format acceptance. Earlier failures below
retain their original verdicts.

Staging `5acc4054`, macOS Console 2022.1: the separate null-source diagnostic
passed **1 test in 9.83s**, followed in a fresh root by the unchanged complete
created-field history case, **1 passed in 7.95s**. Both source variants and
their undo effects passed independent checks. The diagnostic itself remains
diagnostic-only; it is not separate full-history coverage. Both runs preserved
source hash/mtime/tree and 1,883 tracked files, deleted passing sandboxes and
left no owned process. These are exact 2022 component results, not generic
class, nested/platform, Fresh or whole-ticket acceptance.

The matching 2021 legacy import collector on `5acc4054` recorded **1 failed in
12.65s**. The saved-project prerequisite now succeeds; the first media/Render
write passed Gateway verification. Independent reading then hit native rejection
of the public `active-source` projection (`Unknown accessor activeSource`).
Its sandbox is quarantined; source integrity and process cleanup passed. This
requires a version-correct public mapping and oracle, not removal of the check.

Two root `1d58f5fa` Authoring startup attempts ended before test collection with
exit 3. The first had a user-observed/user-accepted EULA; the second used the
user-requested child-only `AK_AUTOMATION_MODE=1`. Readiness reached a malformed
client `getInfo` result after 58.93s / 3.85s, respectively. Neither passed the
exact host/build guard. Source full hash/mtime and 1,883 tracked files remained
unchanged and owned processes ended. These are diagnostic evidence, not passing
tests. Exact roots and limitations are in
[native follow-ups](../docs/plans/full-waapi-coverage/NATIVE_FOLLOWUPS.md).

## 2026-10-18 full-coverage R33 integration and history

Integrated runtime `51906536` passed one central preflight: **825 passed**
(30.82s), followed by **8 selected integration checks passed** (22.37s).
Both runs preserved 1,883 tracked files and left no owned processes. Serial
inventory generation/checks passed; the Program roster is 262. These focused
runs do not replace the outstanding full Program and Non-live gates.

Created-field history at component `854d28aa` passed on matching macOS Console
2023.1, 2024.1 and 2025.1: **1 passed** per version in 16.31s, 10.00s and
19.71s. Each retains both original five-field creation/undo/redo cases, with
existing or null Attenuation. Source hash/mtime/tree and 1,881 tracked files
were unchanged; passing sandboxes were deleted and owned processes ended.

The same collector on integrated `51906536`, Wwise 2022.1, recorded **1 failed /
1 warning** (23.63s). Existing-reference creation and undo passed. Null-reference
creation returned no native acknowledgement during transport loss, but Gateway
incorrectly recorded accepted execution; verification then could not connect.
Its effect remains unknown. Source hash/mtime/tree and 1,883 tracked files were
unchanged, processes ended and the failed sandbox was quarantined. The original
root `created-history-51906536-2022-r1` is preserved without replay. See
[native follow-ups](../docs/plans/full-waapi-coverage/NATIVE_FOLLOWUPS.md) for
the original candidate/path boundaries. No Fresh, Windows or whole-ticket
acceptance follows from these results.

## 2026-10-18 full-coverage R32 native components

Voice creation at `b560eaab` passed the exact collector separately on macOS
Console 2021.1–2025.1: **1 passed** per version in 10.90s, 5.60s, 5.85s, 5.92s
and 6.89s. Ordinary root/nested effects apply to all five; the third object.set
effect applies only to 2022–2025. Each original category seals its observation
file hash. All source hash/mtime/tree and 1,882 tracked-file checks passed,
sandboxes were deleted and no owned process remained. No media, Windows or
Fresh evidence is implied.

At `98c1f74f`, one 2025 Render clearing diagnostic passed (14.33s), observing
both flags cleared by one first-slot setter. Its category remains diagnostic-only
and blocked for business acceptance. Source hash/mtime/tree and 1,881 tracked
files were unchanged; sandbox deletion and process cleanup passed. Other
versions and the successor suffix planner are not certified by this result.

Separate matching diagnostics at `a4936b07` passed on 2023.1 (13.11s) and
2024.1 (8.23s), observing the same clearing transition with complete scoped
preservation. Source hash/mtime/tree and 1,881 tracked-file checks, sandbox
deletion and process cleanup passed. These remain diagnostic observations,
not legacy or successor-planner acceptance.

## 2026-10-18 full-coverage R31 native component

At fixed `5e22e208`, the existing anonymous EffectSlot construction case passed
once on each macOS Console 2023.1, 2024.1 and 2025.1: **1 passed** in 16.92s,
19.27s and 22.24s, respectively. Each case independently verifies three effects
through 164 public calls; setup receives no effect credit. All three source
hash/mtime/tree and 1,882 tracked-file checks passed, sandboxes were deleted and
no owned process remained. The earlier contradictory Render request remains a
separate failed/quarantined result. These are exact modern construction results,
not legacy, import, clearing/suffix, history, Fresh or whole-ticket acceptance.

The separate created-field history tracer at `807f33e7` on macOS 2025.1
recorded **1 failed** (11.36s). Sound creation was rejected before dispatch by
the new-object non-master-bus visibility proof; undo/redo were not reached.
The setup Attenuation was verified without history credit. The original failed
sandbox remains quarantined; source hash/mtime/tree and 1,881 tracked files
were unchanged and no owned process remained.

## 2026-10-18 full-coverage R30 component results

Hosted preflight on published `03f5ef62`: **825 passed** (64.76s), run
39097821039. This is a completed preflight, not the full Program/Non-live gate.

The existing RTPC graph case passed separately on macOS Console 2023.1,
2024.1 and 2025.1 at `e2bbf7e5`: **1 passed** in 25.26s, 22.73s and 23.66s.
The 2022.1 attempt there failed (12.17s) because shared-target classification
rejected a valid independent parameter before the first intended effect.
Version-specific repair `567a9fd3` passed that 2022 case: **1 passed** (24.29s).
Every passing case verified five effects, kept source hashes/mtime/tree and
1,881 tracked files unchanged, deleted its sandbox and left no owned process.
These are component results on two candidates, not a single-candidate matrix.

The separate anonymous EffectSlot constructor at `e2bbf7e5` on 2025.1 remains
**1 failed** (8.05s), quarantined: a later Render=true automatically changed an
earlier requested Render=false. The Gateway's cross-slot condition repair is
pending. Source integrity and process cleanup passed. No Fresh, Windows,
2021 RTPC-construction or whole-ticket acceptance is added.

## 2026-10-18 full-coverage R29 checkpoint

Central `90e63ad9`: **824 passed / 1 failed** (30.13s). The sole failure was
the non-object-set schema seal for four approved createPlugin Folder disclosures.
On test-only successor `96660a68`, that exact node passed (0.48s), then the
separate approved cross-focus passed **9 tests** (11.74s). These are separate
runs, not a single 825-pass claim. Source stayed unchanged and owned processes
ended. Serial generators/checks passed; the fixed Program roster is now 261.
Public counts remain 897 version rows / 228 URIs / 515 contracts / 32,978
branches. Native obligation/owner/requirement/policy bytes remain unchanged.

Native macOS 2025.1 RTPC graph case on `96660a68`: **1 failed** (20.42s).
Four effect phases passed both Gateway and independent verification; replaceAll
was accepted but its Gateway ordered-membership assertion used a GUID-sorted
snapshot; the raw native accessor actually preserved request order. The whole
case remains FAIL/quarantined. Source full hash, mtime/tree and 1,881 tracked files were unchanged; owned processes ended.
No Fresh, Windows, full-gate or whole-ticket pass follows. Authoring startup
remains unresolved after bounded owned diagnostics; historical direct-Wine argv
is retained, and its partial process sample grants no business acceptance.

## 2026-10-18 full-coverage R28 checkpoint

Frozen `4fac9727` passed the central preflight **825 tests** (27.01s) and
the separate affected cross-focus **8 tests** (4.26s). Both runs preserved all
1,878 tracked files and left no owned processes. Program roster: 259 entries.
This is not a replacement full Program or Non-live gate.

The same candidate passed one native anonymous EffectSlot exact-ID edit case
on each of macOS Wwise 2023.1, 2024.1 and 2025.1, sequentially: **1 passed**
in 13.04s, 13.29s and 9.71s respectively. Each case independently checked two
separate effects and preservation; source hashes/mtime/tree stayed unchanged,
the sandbox was deleted and owned processes ended. The original `f4c245b6`
2025 failure remains a failure: its collector assumed the wrong embedded
Effect owner/parent relationship and stopped before the intended effects.
These results do not establish new anonymous List construction, inline merge,
RTPC graph effects, history effects, Windows or Fresh acceptance. See the
[implementation checkpoint](../docs/plans/full-waapi-coverage/IMPLEMENTATION.md#twenty-eighth-integration-checkpoint).

## 2026-10-18 full-coverage R27 checkpoint

Central `cb35b9d7` recorded **824 passed / 1 failed** (27.28s). The shared-schema
wording repair preserves unrelated operation contracts; its exact failed check
plus five integration checks passed on `b06dfe1c`: **6 passed** (5.92s). Source
stayed unchanged and owned processes ended in both runs. The Program roster now
contains 258 entries; no new full Program or Non-live result is claimed.

Separate earlier `8e9b9f17` completed one read-only 2021 RTPC identity/metadata
diagnostic: **1 passed** (9.52s), ten public calls, source unchanged, sandbox
removed and owned processes ended. Its business category remains blocked;
existing identity/metadata does not establish RTPC construction or effects.
No Fresh or Windows run is added. See the
[implementation checkpoint](../docs/plans/full-waapi-coverage/IMPLEMENTATION.md#twenty-seventh-integration-checkpoint).

## 2026-10-18 full-coverage R26 checkpoint

Frozen `3c3423eb` passed central preflight **825 tests** (27.22s) and a separate
cross-feature focus **8 tests** (7.89s). Both source snapshots were unchanged,
with no owned processes remaining. The actual Program roster has 257 entries.
A separate exact 2025.1 media-result program capture passed **1 test** (1.13s);
its full-product overlay records program proof and missing native proof, not
completed coverage. Both overlay generation and identical check returned
expected exit 2 while other obligations remain open.

Authoring diagnostic `a79ef03b` failed before launch; repaired `f4abca75` launched
but timed out before WAAPI readiness. Both source projects stayed unchanged;
the latter's owned process cleanup completed. Neither is a native business PASS.
No new full Program, Non-live, Fresh or Windows result is added. See the
[implementation checkpoint](../docs/plans/full-waapi-coverage/IMPLEMENTATION.md#twenty-sixth-integration-checkpoint).

## 2026-10-18 full-coverage R25 checkpoint

The complete five-version Program gate at `55383f8c` ended **12,245 passed /
168 failed / 4 skipped** (4,131.32s). R25 fixes have scoped passing successors
for those original failures; no replacement full-gate PASS is claimed.
Central `7228c25f` recorded **820 passed / 5 failed**; combined repair focus
`0311ab60` recorded **208 passed / 1 failed**, including the five central repairs;
`883fd0c7` then passed the sole remaining metadata-drift error-fixture node.
All source snapshots were unchanged and owned processes ended. Counts are not
summed into a single-candidate gate. The actual Program roster has 256 entries.

Exact earlier `6ca8d96c` passed one prospective AuxBus reference case on each
supported native version. Existing-source reference/scalar/create-merge and the
new optional saved None-state handling still need matching native proof.
No Fresh or Windows run is added. See the
[implementation checkpoint](../docs/plans/full-waapi-coverage/IMPLEMENTATION.md#twenty-fifth-integration-checkpoint)
for retained failures and scope limits.

## 2026-10-17 v1.1 repair checkpoint

Candidate `e8ca72d3` passed Program **6942 / 3 skipped** and Non-live
**18009 / 127 skipped / 34 deselected**, both exit 0. Later test-framework
repairs received focused validation, not relabeled full-gate runs. Native
component tests cover all five GameParameter/dependency lanes and supported
2022.1–2025.1 standalone ShareSet lanes, with an explicit 2021.1 boundary.
Ten approved actual Fresh attempts provide cumulative business PASS for all four
workflows across separately frozen candidates and roots, not one four-case PASS
root. F4's selected 1/1 root and final F2's selected 1/1 root passed identical
verify-only. Candidate `0b063181` passed F3 and failed F2 (selected 1/2); the
unchanged product/harness at evidence-only successor `62d19e1c` then passed F2.
Final routing-disclosure regression passed 987 tests / 11 Windows-only skips;
this is not a repeated full gate. See the
[dated acceptance record](../docs/research/waapi-v11-repairs-acceptance-2026-10-17.md)
for exact candidates, original failures, retained evidence and review.
No native-Windows acceptance is claimed.

## 1.1.0 release validation (2026-10-10)

The seven-workflow `integration_expansion_v1` selection has cumulative business
acceptance for all 13 positive units on both macOS and native Windows, plus the
separate EXP22-M05 capability boundary. This combines explicitly identified
candidates/roots; it is not a single-candidate or single-root automated 13/13.

- **macOS:** the [completion record](../docs/research/integration-expansion-acceptance-2026-10-09.md)
  records all 13 business outcomes, the raw full-root 12 PASS / 1 notice FAIL,
  and the later targeted C09 PASS with identical verify-only. The latest full
  macOS Non-live result remains the dated `5562104` entry below.
- **Windows baseline:** the [assessment](../docs/research/windows-expansion-assessment-2026-10-10.md)
  retains `7b4e1164`'s raw 9 PASS / 4 FAIL across four roots: 11 business
  completions and two C08 operations rejected before execution. M05's valid
  unnamed-object discovery defect was repaired and program-tested; its already
  proven business result was accepted without another Fresh attempt.
- **Windows repair:** [targeted acceptance](../docs/research/windows-agent-command-escaping-2026-10-10.md#native-windows-acceptance-closeout)
  on `56339bb1` completed C06/2022 and C08/2022/2025 with all independent
  business checks and all 55 command reconciliations passing. Raw results are
  2 PASS / 1 ancillary-progress-notice FAIL. The latter remains frozen without
  verify-only. All source hashes/mtimes were unchanged, passing sandboxes were
  removed, failed evidence retained, and scoped processes/jobs cleared.
- **Windows developer limits:** the [portability report](../docs/research/windows-expansion-portability-2026-10-10.md)
  records the original failed full collection and focused repairs. No new
  all-green full native-Windows Non-live run is claimed; one retired-Composer
  transport fixture remains a documented nonblocking failure. Focused selections
  overlap and are not summed into a new total.

This is reliability and workflow validation, not additional reflected-API or
exhaustive parameter coverage. Full Playlist/Transition authoring, audible
playback acceptance and detailed expansion phase timing are not delivered by
this evidence. [Business acceptance](semantic/TEST_ACCEPTANCE.md) governs new
rerun decisions; historical verdicts stay unchanged.

## Runner modes and strict real behavior

### 2026-10-09 Expansion completion under targeted business acceptance

Candidate `5562104` passed Full Non-live: **17254 passed, 120 skipped,
27 deselected** (920.46s), exit 0. Affected discovery-repair focused validation
passed 360 tests; both independent review findings closed. Product Skill bytes
remain unchanged. These developer gates grant no additional per-API/live credit.

Fresh macOS EXP25-C09 passed six business assertions and actual v8 notice review,
then identical successful-root verify-only with 84 byte-identical root files.
All 69 artifacts and 11 seals validated; source full hash/mtime were unchanged,
the passing sandbox removed and temporary job/scoped processes cleared.

The earlier `8079061` full root retains 12 overall PASS / 1 notice-only FAIL plus
separate EXP22-M05 boundary. All 13 positive business outcomes passed. The user
explicitly approved closure after the repaired targeted run without another full
matrix; this is not a final-candidate full-matrix PASS or a historical regrade.
Detailed phase timing is deferred. See the [acceptance report](../docs/research/integration-expansion-acceptance-2026-10-09.md)
and [machine-readable record](../docs/research/integration-expansion-acceptance-2026-10-09.json).


### 2026-10-01 Pristine-Draft regression and music read investigations

Frozen macOS candidate `cc8707a` passed Full Non-live:
**12044 passed, 118 skipped, 27 deselected** (777.20 s), exit zero.
Logs/JUnit digests are in [the completed gate record](../docs/research/integration-expansion-pristine-draft-gates-2026-10-01.json).

Six copied-project public read investigations completed: three on 2025.1
(3 passed / 32 deselected, 11.45 s) and three on 2022.1 (3 passed / 32
 deselected, 15.40 s). Every source full hash, mtime, tree metadata and scoped
cleanup check passed; investigation copies were deleted. These are completed
bounded investigations, **not complete music authoring or Agent acceptance**.
Read failures, clarification, unavailable representations and unproven order
remain findings. The omitted property-state platform was a probe input error,
not an upstream boundary. See [music read findings](../docs/research/integration-expansion-music-read-findings-2026-10-01.json).

The narrow platform correction passed 35 focused fake-client tests. The new
existing-2025-reference goal passed 23 focused tests after independent order
and evidence-bound review repairs; it has not run live yet. Neither adds
Agent credit or silently changes the formal seven-case selection.

### 2026-10-01 Expansion receipt binding and completed regression

Frozen macOS candidate `dd1ad71` (harness implementation `7c81406`) passed
Full Non-live: **11998 passed, 118 skipped, 27 deselected** (784.07 s), exit zero.
JUnit reports zero failures and errors. This is program/harness evidence;
it grants no live-Wwise or Fresh Agent business acceptance.
See [completed gate records](../docs/research/integration-expansion-read-receipt-gates-2026-10-01.json).

Its Luna-high C01 pilot retained an ordinary model input FAIL: the Agent omitted
the required GUID braces during object binding. The authenticated command was
rejected before dispatch; no Preview or project change occurred. Source full
hash and mtime remained unchanged and the failed copy was quarantined. Negative
archive validation stopped the batch, leaving C06/M01 pending. The model
comparison remains incomplete; no Gateway grammar relaxation is justified.
See [pilot evidence](../docs/research/integration-expansion-invalid-bind-pilot-2026-10-01.json).

### 2026-10-01 Fresh workspace repository-boundary repair

Frozen macOS harness candidate `d78be5b` completed Full Non-live:
**11967 passed, 1 failed, 118 skipped, 27 deselected** (788.75 s), exit one.
The sole failure was the inventory document's lowercase `full Non-live` label;
its newest dated evidence did not match the documented count assertion.
The label is corrected in the documentation-only follow-up. This is **not a
single all-green full Non-live run**; preserve the failed log and JUnit.
The focused documentation rerun passed **9 tests**, exit zero. The follow-up
changes documentation only; the broadly tested harness and Skill bytes remain
unchanged. No additional passing full-run count is inferred.

The targeted workspace checks passed **18 tests**; the full harness file passed
**381 tests, 9 native-Windows-only skips**. Independent Spec and Standards
reviews reported no actionable findings. The minimal valid Git boundary uses
fixed local metadata, rejects drift and external links, and bounds metadata
reads without adding a Git executable dependency.

CLI-only startup probes passed with the valid boundary; they grant no Agent
or Wwise business PASS. The prior Luna pilot retains three pre-exec prompt-audit
FAILs, with unchanged source hashes/mtimes and quarantined copies. The new
Luna-high / GPT-6.1-Sol-medium comparison and final macOS acceptance remain
pending. See [startup diagnostics](../docs/research/integration-expansion-startup-diagnostics-2026-10-01.json).

### 2026-10-01 Outcome-based integration expansion: development gates

Frozen macOS candidate `9256ae8` passed the fixed five-version Program gate:
**5886 passed, 2 skipped** (275.05 s), and Full Non-live:
**11954 passed, 118 skipped, 27 deselected** (809.03 s), both exit zero.
The two Program skips require native Windows. Earlier interrupted/failed gate
roots remain retained; failed-only fixture reruns preceded this complete pass.
The final tests correct fake-CI interpreter isolation, local LFS hydration,
host-dependent Wine mapping expectations, per-field evidence bounds, and
compact verification proof; these are not additional live API coverage.

Real copied-project preparation passed 13 baselines plus the separate
M05/2022 capability boundary. Developer-owned M01 music import and C06 existing
RTPC updates passed on 2022.1/2025.1 with approved immutable Previews, single
execution, Gateway verification, and independent outcome checks. Source full
hashes/mtimes/tree metadata and scoped cleanup were proven. This is **not Agent
semantic acceptance**. The matching 2025.1.7 Console smoke passed, with 4.41 s
readiness and cleaned/deleted test copy.

The six-task Luna-high / GPT-6.1-Sol-medium pilot remains pending: its first
one-shot launcher blocked in file-open before creating a campaign root while
the Mac was locked. No Agent or Wwise case started; the job was unloaded and
the diagnostic retained. No new Windows or playback evidence is claimed.
See [development gate records](../docs/research/integration-expansion-development-gates-2026-10-01.json),
[native follow-ups](../docs/research/integration-expansion-native-followups-2026-10-01.json),
and [music investigation dispositions](../docs/research/music-expansion-dispositions-2026-10-01.md).

### 2026-09-14 Portable Skill entry and scoped first-use validation

The public description now uses query/edit/subscribe/monitor language and
loads references from the supplied Skill root, without a hardcoded installation
directory or agent-brand bootstrap. No WAAPI business runtime changed.
Program at `1e9ab36`: **5766 passed, 2 skipped**.
Full Non-live: **11430 passed, 116 skipped, 27 deselected**, exit zero at
`519c47b` (767.49 s). Both owned read-audit/first-use regression files passed
**383 tests, 9 native-Windows-only skips**.

On both macOS and native Windows, `1e9ab36` passed the two bare first-use tasks
(`/waapi-skill` and a Markdown Skill link) plus their two same-thread follow-up
turns: one offline `config-show` and complete welcome facts initially, no
command or repeated welcome afterward. The packaged Skill remained identical
at `519c47b`. The existing offline C1 matrix also passed one Fresh task per
host: macOS at `1e9ab36`, Windows at `519c47b`, proving coverage-reference
selection and an absolute Gateway runner. All Fresh tasks used Terra, medium
reasoning, default service tier, and isolated memory-off environments.

These are scoped first-use and matrix results, not a full campaign/replay or
real-Wwise acceptance. Earlier grader failures, the genuine Windows relative-
runner failure, and pre-Agent campaign-wrapper blocks remain recorded in the
[validation report](../docs/research/portable-skill-entry-validation-2026-09-14.md).
No Wwise process or project mutation ran; temporary launch tasks/scripts were
removed and owned residual checks were empty.

### 2026-09-14 Cross-object-family CRUD regression and repair

macOS WwiseConsole candidate `b2c7afb` passed **13 selected tests on each of
2021.1–2025.1: 65/65**, using disposable copies and the public Gateway. These
include explicit prohibited/unsupported boundaries, not 65 working mutation
capabilities. The coverage adds multilingual Voice reimport, Bus/AuxBus,
State/Switch, Attenuation, music-container hierarchy, derived object identity,
versioned Stinger references and Effect-slot preservation. It does not prove
Playlist/Transition authoring or audible playback.

There were **149 business-verified transactions**, plus four 2021 fixture-save
transactions with only result-schema verification. All source hashes, mtimes
and tree metadata remained unchanged; passing sandboxes were deleted and
scoped residual-process lists were empty. Generic owned-list clearing also has
eight fake-WAAPI public-Gateway regressions, not additional live coverage.

Final Program at `e19fff1`: **5766 passed, 2 skipped**.
Full Non-live: **11347 passed, 116 skipped, 27 deselected**, zero failures at
`b10b95e`. The
packaged Skill and real-test files remained identical across these candidates;
intervening changes corrected old schema/count test expectations. Earlier
failed runs remain documented in the [repair record](../docs/research/crud-object-family-regression-2026-09-14.md).
No Fresh Agent or native-Windows test was run for this change.

### 2026-09-14 Music Track import owner and verification repair

Runtime candidate `af783b7` passed macOS Program: **5266 passed, 2 skipped**.
Focused import Adapter/Gateway/Registry/verifier files: **615 passed**.
Full Non-live: **10840 passed, 2 failed, 113 skipped, 27 deselected**. The two
failures concern dated inventory wording and a README installation command
changed by independent commit `cbf60ee` during the run. Packaged Skill bytes
remained unchanged. Current README verification and the corrected dated-record
test passed in a **23-test** focused follow-up. This is **not a single all-green
full Non-live run**, nor an immutable all-suite candidate result.
Five-version copied-project music import evidence and the separate Sol/High
Authoring preview are detailed in [the repair record](../docs/research/music-import-topology-repair-2026-09-14.md).
Exact candidate `9df82a77c3b31c1e943ebef278a6497f738f5668` passed both public
Gateway music workflows on each version, **10/10** on macOS WwiseConsole.
All ten music transactions verified; source hashes/mtimes were unchanged, passing
sandboxes were deleted and scoped residual-process checks were empty.
No native Windows or full Fresh Agent campaign was run for this repair.

### 2026-09-13 Authoring entry and safe-switch repair

Code candidate `249fc75` aligns compact version-aware business discovery,
Skill/lane guidance and project open/close defaults. Omitted discard now keeps
the Wwise save prompt enabled. The five-version regressions cover omitted and
explicit choices; the project-transition matrix includes all six new 2024/2025
rows plus cancellation/timeout boundaries. No real Wwise or Fresh Agent ran.

Final macOS Program: **5159 passed, 2 skipped** (native Windows-only skips).
Full Non-live: **10725 passed, 10 failed, 113 skipped, 27 deselected**. All ten
failures were old test expectations for removed native-input documentation,
historical counts, or the pre-addition call allowlist. Following test-only
corrections, all three affected test files passed **91 tests**. Runtime and
Skill files did not change after Program. This is a complete Non-live run plus
focused follow-up, **not a single all-green full Non-live run**.
See [audit and repair evidence](../docs/research/skill-to-dispatch-audit-2026-09-13.md).

### 2026-09-13 approved Authoring core additions

Nineteen version/function rows (nine in 2024.1, ten in 2025.1) reuse the
existing closed Gateway routes; Console inventory remains unchanged. Final
macOS Program: **5061 passed, 2 skipped**. Focused Non-live (CI driver, new core
Gateway regressions, and host/project Adapter): **151 passed, 11 skipped**.
Both sets of skips require native Windows and receive no passing credit.
Real Windows Authoring, called from the macOS Gateway, returned valid empty
selection results for `selected` on both versions and `getSelectedFiles` on
2025.1. No real mutation, native-Windows Python gate, Fresh Agent, full Non-live
or live matrix was run. See [scope and evidence](../docs/research/authoring-core-scope-2026-09-13.md)
for exact exclusions, historical failures, and validation limits.

### 2026-09-13 CRUD field Interface repair

The field-selection cutover adds 53 public Gateway regressions in
`tests/unit/test_field_interface_closure_gateway.py` and includes that file in
the fixed Program manifest. Final macOS Program: **5011 passed, 2 skipped**.
The full Non-live invocation reported **10598 passed, 2 failed, 113 skipped,
27 deselected**; both failures were obsolete operate-reference assertions and
passed after correction in a 146-test focused selection. Preserve the original
full-run failure classification. No Fresh Agent or actual Wwise was started.
See [repair evidence](../docs/research/crud-field-interface-repair-2026-09-13.md)
for the precise candidate/run scope and subsequent focused validation.

### Mode definitions

| Scope | Type | Files / Nodes | What it verifies | Real Wwise required |
| --- | --- | --- | --- | --- |
| Focused pure-program gate | Unit, contract, and fake gateway | `ci/test.sh --mode program` | Runs the five-version public-route coverage contract, all 808 default-profile version/API program cases, the deterministic 824-row full-surface release report, the separate Authoring-overlay/resource contracts, negative gateway contracts, isolated-I/O confinement tests, named object/plug-in/import/SoundBank/debug/Lua/UI-command operation contracts and verifiers, RTPC capacity boundaries, the optional registry-integrity file when present, and the selected complete fake preview/confirm/execute/verify chains | No |
| Default non-live suite | Unit and contract | `ci/test.sh --mode nonlive`, equivalent to `poetry run python -m pytest -m "not live and not destructive"` | Fast checks for dispatcher behavior, manifest resources, semantic builders, safety gates, docs contracts, and planning resources | No |
| Full local suite | Unit plus strict real matrix | `ci/test.sh --version all --mode all -- -q -ra` | Runs the non-live suite first, then the strict real matrix across 2021.1, 2022.1, 2023.1, 2024.1, and 2025.1 | Yes for the matrix half |
| Full strict real matrix | Live plus destructive | `ci/test.sh --version all --mode matrix -- -q -ra` | Sequential real Wwise coverage for 2021.1, 2022.1, 2023.1, 2024.1, and 2025.1 focused live and destructive nodes | Yes |
| 2021 live focused run | Live | `ci/test.sh --version 2021.1 --mode live -- -q -ra` | Read-only 2021.1 prerequisites, reflection, WAQL object get, and safe object topic behavior | Yes |
| 2021 destructive focused run | Destructive | `ci/test.sh --version 2021.1 --mode destructive -- -q -ra` | 2021.1 copied sandbox mutation, soundbank/audio, and SwitchContainer assignment behavior | Yes |
| 2022 live focused run | Live | `ci/test.sh --version 2022.1 --mode live -- -q -ra` | Read-only 2022.1 prerequisites, reflection inventory, and WAQL object get behavior against the immutable `tests/_org/2022.1` fixture copy | Yes |
| 2022 destructive focused run | Destructive | `ci/test.sh --version 2022.1 --mode destructive -- -q -ra` | 2022.1 copied sandbox mutation, undo, soundbank/audio, and SwitchContainer assignment behavior using a per-test copy of `tests/_org/2022.1` | Yes |
| Smoke | Strict real launch probe | `ci/test.sh --version all --mode smoke` | HeadlessLifecycle starts WwiseConsole, waits for WAAPI readiness, calls `ak.wwise.core.getInfo`, and shuts down | Yes |
| Fresh Codex screening | Formal memory-off Codex v2 semantic campaign | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile screening --campaign-root skills/waapi-skill-workspace/campaign-screening` | Runs 40 fresh isolated sessions with immutable input fingerprints, append-only attempts, broker-reconciled gateway commands, and hard-gate grading | Yes for live cases |
| Fresh Codex formal sample | Formal memory-off Codex v2 semantic campaign | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile formal_98 --campaign-root skills/waapi-skill-workspace/campaign-formal-98` | Runs the declared 98-session formal sample with resume-safe atomic pairs; incomplete or quota-blocked evidence is infrastructure state, not a Skill verdict | Yes for live cases |
| Fresh Codex full cross-version matrix | Formal memory-off Codex v2 semantic campaign | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile full_cross_version_168 --campaign-root skills/waapi-skill-workspace/campaign-full-cross-version-168` | Runs the declared 168-session five-version matrix with one scoped child lifecycle per version, including all six packaged fixed reads; completion requires sealed accepted evidence and passed hard gates for every expected unit | Yes for live cases |
| Fresh Codex heavy API matrix | Formal memory-off Codex v3 semantic campaign | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile heavy_cross_version_80 --suite skills/waapi-skill/evals/suite-v3.json --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root <new-campaign-root>` | Runs 80 approved real-business scenarios for 16 heavy APIs, with five scenarios per API, fresh isolated Codex tasks, sequential Wwise sandboxes, semantic assertions, cleanup, and sealed evidence. Current mutation cases use the canonical `ask_before_changes` authorization path and exact `preview --apply --request-json` argv. | Yes |
| Fresh Codex compound-heavy matrix | Formal memory-off Codex v3 semantic campaign | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile compound_heavy_cross_version_24 --suite tests/semantic/data/compound-heavy-v1/profile.json --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root <new-campaign-root>` | Runs 12 reviewed compound mutation scenarios on both Wwise 2022.1 and 2025.1: two each for `audio.import`, `audio.importTabDelimited`, `object.create`, `object.set`, `soundbank.generate`, and `soundbank.setInclusions`. Every one of the 24 version/scenario units uses a fresh memory-disabled task, a disposable Wwise project, real business assertions, and lifecycle cleanup or sealed failure quarantine. | Yes |
| Fresh Codex integration workflows | Formal memory-off Codex v3 semantic campaign | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile integration --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root <new-campaign-root>` | Runs Weather, Alarm, Harbor, Rifle, Footsteps, and Weapons once on Wwise 2022.1 and once on 2025.1: 12 fresh tasks, 36 user turns, and 20 separately previewed transactions. Fixed committed baselines apply only to Rifle, Footsteps, and Weapons. All units retain hidden business assertions, source-project immutability, and cleanup or quarantine. | Yes |
| Fresh Codex modification-policy matrix | Formal memory-off Codex v3 semantic campaign | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile modification_policy_9 --campaign-root <new-campaign-root>` | Runs nine fixed Wwise 2022.1 tasks: `read_only`, `ask_before_changes`, and `allow_changes` three times each, for 15 isolated Codex CLI invocations. It reuses the reviewed object.create fixture/oracle and validates per-turn unchanged state, concrete policy messaging, exact authorization flow, one-shot cleanup, and zero/one primary dispatch as appropriate. | Yes |
| Fresh Codex deep-interface MVP | Formal memory-off Codex v3 semantic matrix | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_matrix.py --profile deep_interface_mvp_8 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --iteration-root <new-root>` | Runs four fixed `audio.import` business families with two natural-language paraphrases each against the real business compiler and immutable Preview builder but a test-only fake read boundary. It proves closed high-level kinds, names, media keys, values, handles, explicit replacement, compiler-owned paths/types/metadata/native rows, and exact continuations without connecting to or changing Wwise. | No |
| Fresh Codex audio-import business Adapter | Formal memory-off Codex v3 semantic campaign | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile audio_import_business_8 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root <new-root>` | Runs Weather, Rifle, Footsteps, and custom-field Weapons with two natural-language variants each through the production `audio.import` business Draft, closed object/field handles, compiler-owned native request, and immutable Preview. Existing user paths cross the Agent interface as ordered name segments; Gateway inserts every Wwise separator. The test-only read boundary starts no Wwise process and permits no execution. | No |
| Fresh Codex object-metadata business Adapter | Formal memory-off Codex v3 semantic campaign | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile object_metadata_business_1 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root <new-root>` | Runs one Alarm Output Bus repair through production `object.setReference`: exact user paths bind to object handles, a short UI meaning discovers one opaque field handle, Gateway emits the staged target/declaration continuation and immutable Preview, and no Wwise process or execution is permitted. | No |
| Fresh Codex Switch-assignment business Adapter | Formal memory-off Codex v3 semantic campaign | `skills/waapi-skill/.venv/bin/python tests/semantic/run_codex_skill_campaign.py --profile switch_assignment_business_1 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --campaign-root <new-root>` | Runs one independent assignment Preview through production `switchContainer.addAssignment`: three natural object paths bind to opaque handles, Gateway derives the exact GUID relationship, opposite precondition, native request, verifier identity, and immutable Preview, and no Wwise process or execution is permitted. | No |
| Authoring UI reflection maintenance | Real read-only resource collection | `skills/waapi-skill/.venv/bin/python tests/maintenance/collect_authoring_ui_commands.py --version <version>` | Against the matching already-running Authoring builds `2021.1.14.8108`, `2022.1.19.8584`, `2023.1.19.8928`, `2024.1.13.9056`, and `2025.1.7.9143`, performs exactly seven calls per version: `getInfo`, five fixed-URI `getSchema` reads, and `getCommands`. Recorded command counts are 317 / 451 / 475 / 594 / 623. It executes, registers, and unregisters zero commands. | Yes |
| Real-launch audit | Evidence inspection after a real run | `wc -l .waapi-skill-state/evidence/waapi-test-remediation/real-wwise-launches.jsonl` and `tail -n 4 .waapi-skill-state/evidence/waapi-test-remediation/real-wwise-launches.jsonl` | Confirms a new real launch appended pid, port, command, sandbox project, `getInfo` version, `ready_duration_seconds`, and cleanup result; the file need not exist before the first run in a cleaned checkout | Generated by real modes |

Strict real modes are `live`, `destructive`, `smoke`, and `matrix`. `all` is a composite runner: it executes non-live first, then the strict real matrix. Strict real modes require an executable `WWISE_CONSOLE` and an existing `.wproj` at `WWISE_SAMPLE_PROJECT_PATH`; these can come from environment variables or the untracked `tests/fixtures/local/live-environment.json` test config (template: `tests/fixtures/local/live-environment.example.json`, override path: `WWISE_TEST_CONFIG`). Missing prerequisites fail before pytest execution. `ready_duration_seconds` measures WAAPI readiness, not the total foreground GUI or plugin warning lifetime.

Repository development and CI-safe tests use Poetry through `ci/test.sh` or
`poetry run`. The Skill runtime and formal semantic campaigns use
`skills/waapi-skill/.venv`; do not install developer test dependencies there or
replace that interpreter with a global Python. The two legacy six-task
integration profile IDs remain available internally only for exact sealed-root
replay and are intentionally absent from the current runner table.

`program` is an all-version code-only gate and uses version `none`. It selects only explicit `tests/unit` files/nodes, clears inherited Wwise runtime and endpoint settings, disables strict-real flags, and rejects additional pytest paths or node ids. It does not collect `tests/semantic`, `tests/live`, or `tests/destructive`; therefore it neither starts Codex nor connects to or launches Wwise.

Fresh Codex v2 is the formal semantic workflow documented in `tests/semantic/README.md`. The campaign wrapper freezes the Skill, suite, harness, live config, Codex binary, interpreter, and immutable options; dispatches the v2 matrix in version batches; and seals append-only attempts before consolidation or resume. It uses the Skill-local Python interpreter, a new Codex CLI process/thread/turn, and disposable `HOME` and `CODEX_HOME` for every phase. A live selection first records a no-install `waapi-client` dependency check in `live-preflight.json` and fails before Codex or WwiseConsole when the current interpreter is unsuitable; pure offline selections skip that check. The runner records memory as disabled and separates proven pre-action service/timeout/quota failures from Skill grading, while authentication and unproven runtime states are blocked. The declared 40/98/168 profile sizes are suite contracts, not claims that a formal or full run completed. Mocked/nonlive pytest coverage is CI-safe but is not a live WwiseConsole validation substitute.

The v3 heavy profile uses the same fresh-process, memory-off campaign boundary but adds a per-scenario business oracle, explicit mutation verification, and disposable Wwise lifecycle cleanup. The completed `h80-release-c38` evidence is sealed against its exact earlier candidate, suite, harness, Codex binary, interpreter, live configuration, and immutable options. Its 80/80 result is historical evidence for that candidate only. The current harness has since migrated mutation previews to the policy-aware authorization contract and exact `preview --apply --request-json` argv; no new 80-case real campaign has been run for this candidate. The old c38 directory must remain unchanged and cannot be cited as current-candidate validation. Neither result is evidence that every V3 scenario, every 2022.1 capability, or every WAAPI URI has received a fresh-Codex real-Wwise run.

The compound-heavy profile is a smaller regression lane for complex batch composition rather than another API-coverage total. The frozen `ch-final24-compact-v4` pass completed all 24 selected units with 22 passes and two safe pre-preview failures. Those failures were a corrupted caller-supplied inline Base64 value and a JSON-escaped Wwise path copied as double literal backslashes; both were rejected before mutation. After narrow operation-schema repairs, the frozen `ch-repair2-compact-v5` campaign passed those exact two units and its identical `--resume --verify-only` audit. Across the two campaign roots, all 24 selected version/scenario combinations have passing evidence for those exact frozen candidates, but this must not be reported as one single-candidate 24/24 campaign or as validation of the current candidate. The initial two quarantined failure sandboxes remain sealed evidence; all passing sandboxes were cleaned, and both source SampleProjects retained identical hashes and mtimes.

The frozen public `integration` candidate
`7f54506783a131695bafb97b89103488cb73d96c` has host-specific cumulative
evidence, not one single-root pass. On macOS, `imac-int-7f54506-r1` passed 7
units and failed 5, `imac-int-7f54506-r2-retry5` passed 4 and failed 1, and
`imac-int-7f54506-r3-rifle` passed its one fresh Rifle unit and its identical
`--resume --verify-only` audit. All 12 unique public-profile units therefore
have macOS passing evidence across those three roots, but no root passed 12/12.

On native Windows, `iwin-int-7f54506-r1` passed 9 units and failed 3. Fresh
root `iwin-int-7f54506-r2-retry3` then passed Weather and failed both Weapons
units, leaving 10 of 12 unique public-profile units with native-Windows passing
evidence. Both remaining Weapons units failed in both roots when the
authenticated Broker rejected malformed preview JSON before the rejected
command reached the runner or Wwise; no mutation occurred. This is not complete
native-Windows `integration` acceptance and must not be reported as Windows
12/12. All four roots containing semantic FAILs were frozen without
verify-only replay. Independently,
`test_native_windows_powershell_shim_preserves_hostile_json` passed both native
Windows parameterizations (2 passed, exit 0), proving exact hostile-JSON
preservation through pwsh -> PS1 -> Broker without granting any semantic PASS
credit. On both hosts every source-project full hash and mtime remained
unchanged, passing sandboxes were removed, failed sandboxes were sealed and
quarantined, and no scoped residual process remained.

The frozen Composer public `integration` candidate
`198a510e49f1215b3c02f6d3108c734fc5c59400` has complete cumulative evidence
on both hosts, but neither host has a single-root 12/12 result. On macOS,
`imac-integration-198a510-r1` passed 11 units and failed INT22 Weather;
`imac-integration-198a510-r2-int22-weather`,
`imac-integration-198a510-r3-int22-weather`, and
`imac-integration-198a510-r4-int22-weather` each preserved one further
ordinary INT22 Weather FAIL,
while `imac-integration-198a510-r5-int22-weather` passed that unit fresh
and then passed identical `--resume --verify-only`. On native Windows,
`iwin-integration-198a510-r1` passed 6 and failed 6,
`iwin-integration-198a510-r2-retry6` passed 5 and failed INT25 Footsteps,
`iwin-integration-198a510-r3-footsteps` preserved another Footsteps FAIL, and
`iwin-integration-198a510-r4-footsteps` passed Footsteps fresh plus identical
verify-only. Thus all 12 unique public-profile units have PASS on the same
frozen Skill/harness candidate on each host, cumulatively across roots. Every
FAIL root was frozen without verify-only; every source full hash and project
mtime was unchanged, PASS sandboxes were removed, and FAIL sandboxes were
sealed/quarantined. Frozen-candidate development gates passed with focused
semantic 464 passed / 4 skipped, Program 2923 passed / 2 skipped, and Non-live
7763 passed / 104 skipped / 27 deselected. Native-Windows focused validation
passed 462 / skipped 6 POSIX-only cases. Commit
`030231b41e623e72f72de785d6bcbc3780d7eb37`
changes only domain/planning docs, one unit test, and the program manifest, so
it does not replace the frozen Skill, suite, runner, or semantic harness.

Pre-review public `integration` candidate
`ebcfde245bcbcacd2b8842e5ec205e7111b86743` completed one independent
single-root 12/12 pass on each host. MacOS root
`imac-int-ebcfde2-r67-full12` and native-Windows root
`iwin-int-ebcfde2-r56-full12` each ran all six workflows on Wwise 2022.1 and
2025.1 with fresh memory-off `gpt-5.6-terra` tasks at medium reasoning and the
default service tier; both roots then passed their identical
`--resume --verify-only` audit. Every one of the 24 lifecycle records is PASS,
the source-project full hash and mtime are unchanged, all passing sandboxes
were removed, and final root-scoped process checks were empty. The macOS
one-shot LaunchAgent and native-Windows `InteractiveToken` / `Limited`
Scheduled Tasks were removed. This is the first current-profile result in this
inventory that satisfies the single-root 12/12 acceptance boundary on both
hosts rather than accumulating credit across repair roots.

Current semantic-harness candidate
`0682c1a979f7ce5bfb648914914b7393148a6495` retains the exact packaged Skill
tree from `0edaf1a` and has complete same-candidate public-profile evidence on
both hosts. Native-Windows root `iwin-int-0682c1a-r63-full12` passed all 12
units in one root and then passed identical verify-only. MacOS root
`imac-int-0682c1a-r73-full12` passed 11 units and failed only INT22 Rifle when
the Agent stopped before Preview despite the third binding response explicitly
reporting `complete=true, truncated=false`; fresh failure-queue root
`imac-int-0682c1a-r74-int22-rifle` passed that unit and identical verify-only
with no candidate, suite, harness, or option change. This is cumulative MacOS
12/12 evidence, not a single-root claim. All 25 lifecycle records preserved
source-project full hashes and mtimes; passing sandboxes were removed, the one
failed sandbox remains sealed, and final process/task/launcher checks were
empty.

The legacy internal `integration_workflows_cross_version_6` component has
cumulative macOS passing evidence for all six unique version/workflow units
across three frozen 2026-07-31 roots. Initial
`a12` passed the two Alarm and two Harbor units and failed both Weather units.
Fresh repaired roots `a20-int22-weather` and `a24-int25-weather` passed the
remaining Weather units, including five Sound imports with properties and
OutputBus references, five Play Events and timed Actions, and a three-point
Volume RTPC. This is not one final-candidate 6/6 campaign. All successful
sandboxes were removed; failed attempts remain sealed and quarantined; source
SampleProject full hashes and mtimes were unchanged in every recorded
lifecycle.

Every legacy root named here and in the 2026-08-03 rerun below seals
`runtime.platform=darwin`; they are macOS evidence. Later cross-host component
runs are recorded below.

On 2026-08-03 the Weather parameter pairs and Harbor SoundBank request were
rewritten in more natural user language without changing transaction topology,
fixtures, or business oracles. A fresh full run passed five of six units; the
2025.1 Alarm failed safely before mutation because the Agent redundantly
re-read the Action rather than following its returned `Target.id`. A narrow
query-reference repair removed that duplicate hop, after which fresh 2025.1
and 2022.1 Alarm roots both passed on the repaired candidate. Weather and
Harbor had loaded only the unchanged operate reference and passed in the full
run. This gives all six revised prompt units passing evidence across roots,
not one repaired-candidate 6/6 run. All eight source hash/mtime checks passed;
passing sandboxes were cleaned and the failed sandbox remains quarantined.

Later reruns still selected the old internal
`integration_workflows_cross_version_6` component, not the public composed
`integration` profile. At commit
`9e75a1aea496abcb9ef2a61e1da685adb99f4b01`, macOS root
`imac-wah-9e75a1a-r1` passed all six component units fresh and passed its
identical `--resume --verify-only` replay. At commit
`9b4de8f618855091a424700b50ab8b0fd1989270`, macOS root
`imac-wah-9b4de8f-r1` passed five units and failed one, while native-Windows
root `iwin-wah-9b4de8f-r1` passed three and failed three; both failed roots
were frozen without verify-only replay. This is exact old-component
provenance, not current `integration` acceptance and not unified 12/12
evidence.

Those v1 integration campaigns predate the public structured/advanced-query migration:
offline `query-schema`, `query-object --request-json` with
`waapi-skill.object-query/v1`, the separately disclosed bounded
`waapi-skill.advanced-object-query/v1`, and mutation identities closed to `id`,
`path`, `exact-type-name`, `direct-child`, and `scoped-name`. Those earlier
results remain valid only for their frozen migration-before candidates.

The 2026-08-03 macOS legacy internal
`integration_workflows_v2_cross_version_6` evidence is
cumulative across frozen roots, not one final-candidate 6/6 run. `r8` passed the two Rifle
units, `r12-2022` passed 2022.1 Weapons, `r23-2022-footsteps` passed 2022.1
Footsteps, and `r24-2025-repairs` passed 2025.1 Footsteps and Weapons. Thus all
six unique units have passing evidence across those roots. Passing sandboxes
were removed, failed or blocked diagnostic sandboxes remain sealed and
quarantined, and every recorded source-project full hash and mtime remained
unchanged. This V2 evidence applies only to those exact newer workflow paths;
it grants no per-API credit and does not prove advanced WAQL or unrelated routes.

The later native-Windows V2 campaign is also cumulative across frozen roots
and candidates. At commit `0dfea2b`, `windows-v2-six-0dfea2b-r1` attempted all
six units: 2022.1 Rifle, 2022.1 Footsteps, and 2025.1 Rifle passed; 2022.1
Weapons, 2025.1 Footsteps, and 2025.1 Weapons failed, so the outer campaign
exited `1` and was not verify-only replayed. At `a516835`, fresh
`a516-w22-r1` repaired 2022.1 Weapons and passed its identical
`--resume --verify-only` replay, while fresh `a516-f25-r1` still failed 2025.1
Footsteps on a metadata-routing detour and was frozen without verify-only. At
`f1b6a51`, fresh `f1b-f25-r1` and `f1b-w25-r1` passed 2025.1 Footsteps and
2025.1 Weapons respectively, and both passed identical verify-only replay.
The 2025.1 Weapons pass reconciled all 12 Broker records, preserved the exact
quoted `@Volume` token, retained an unchanged source, and removed its passing
sandbox. Thus all six V2 units now have native-Windows passing evidence across
these roots, but there is no one-root or one-candidate Windows 6/6 run.

For Switch assignments, runtime candidate
`d05f1ecdc3b33fca83866e75669c65039877edd6` passed macOS Program
`3655 / 2 skipped`, native-Windows Program `3642 / 15 skipped`, and macOS
Non-live `8632 / 110 skipped / 27 deselected`. Its closed add/remove workflow
passed on native Windows against Wwise 2022.1 and 2025.1, one selected node per
version. Route-only candidate
`d45f75f5e75190d5b4e607a02aee2dcf38e73ab9` then passed macOS Program
`3655 / 2 skipped` and the same real workflow on macOS 2022.1 and 2025.1.
Fresh roots `imac-sab-d45f75f-r2` and `iwin-sab-d45f75f-r2` each passed
the one-unit `switch_assignment_business_1` profile and an identical
`--resume --verify-only` audit. Their eight accepted commands exposed only
the three business-object bindings before Gateway-owned materialization; no
Wwise process started and no project changed. Earlier roots
`imac-sab-d05f1ec-r1` and `iwin-sab-d05f1ec-r1` remain frozen semantic
FAILs: the Agents invented `switchContainer.assign` and
`switchContainer.assignSwitch`, respectively, and the Broker rejected the
first operation command before Gateway dispatch. Temporary LaunchAgent and
Windows Scheduled Task resources were removed, and both hosts reported zero
scoped residual processes.
After the entry Skill was compacted without changing Switch routing, exact
packaged-Skill candidate `b544197fb6b7455814fbb2079043a5a354daca59`
repeated the same one-unit PASS plus identical verify-only in macOS root
`imac-sab-b544197-r1` and native-Windows root `iwin-sab-b544197-r1`.
Both current roots retained their sealed attempt manifest, started no Wwise
process, created no project mutation, removed their temporary launch resources,
and ended with zero scoped residual processes.

Final deepened candidate `c874917220cb7723d60f86a14cea72c5d15cca52`
passed `switch_assignment_business_1` fresh plus identical verify-only in
macOS root `imac-sab-c874917-r1` and native-Windows root
`iwin-sab-c874917-r1`. The Gateway supplied one complete copy-ready
`draft-start`, followed by exact role-bound continuations for
`switch_container`, `child`, and `state_or_switch`; both Agents reached one
Preview without starting Wwise or mutating a project. Windows used temporary
`InteractiveToken`/`Limited` Scheduled Tasks for both runs. Both hosts ended
with zero scoped residual processes and Windows retained zero matching tasks.
Exact Program candidate `4c55ba6b53eeb4beff97e7b590686d78da7e612e`
passed macOS `3659 / 2 skipped` and native Windows `3646 / 15 skipped`;
`c874917` changes only semantic evidence/protocol tests. MacOS Non-live at
`d10dc23c4dd95eb865a5a768ac8a4e0885e6a233` passed
`8639 / 110 skipped / 27 deselected`. Later packaged changes are limited to
copy-ready business start/role continuations and compact audio-import receipts;
exact focused carry passed 410 tests at `4389b6c`, 452 / 4 skipped at
`4c55ba6`, and 76 at `c874917`. Switch native dispatch and verification are
unchanged. Failed Mac diagnostic root `imac-sab-d10dc23-r1` stopped after a
successful schema read without issuing `draft-start`; it is frozen without
verify-only and contributes no PASS credit.

The Authoring UI resource collection made 35 read-only calls in total. Its
command inventories are build/project/plugin/add-on snapshots, not runtime
allowlists. It proves the five fixed schemas and inventory capture only; it
does not prove the GUI/project effect of `execute`, nor any live
`register`/`unregister` behavior.

## Strict real matrix node inventory

Collected with `ci/test.sh --version all --mode matrix -- --collect-only -q`. The command collected 60 version-scoped invocations without running test bodies: 20 focused live invocations and 40 destructive invocations.

| Scope | Type | Files / Nodes | What it verifies | Real Wwise required |
| --- | --- | --- | --- | --- |
| 2021.1 live | Live prerequisite | `tests/live/test_2021_1_live_prerequisites.py::test_2021_1_live_read_only_prerequisites_validate_exact_get_info_before_matrix` | Confirms the exact 2021.1 live Wwise and SampleProject prerequisites, then records read-only `getInfo` proof before matrix work | Yes |
| 2021.1 live | Live reflection | `tests/live/test_2021_1_reflection_prerequisites.py::test_2021_1_live_reflection_prerequisites_and_resource_generation` | Runs 2021.1 reflection against the sandbox and generates resource evidence from the real runtime | Yes |
| 2021.1 live | Live WAQL | `tests/live/test_2021_1_object_get_matrix.py::test_2021_1_live_waql_object_get_matrix_runs_read_only_against_sandbox` | Exercises read-only WAQL object get cases against the 2021.1 sandbox | Yes |
| 2021.1 live | Live topics | `tests/live/test_2021_1_object_topics_sandbox.py::test_2021_1_live_safe_object_topics_against_sandbox` | Checks safe object topic behavior in a 2021.1 sandbox without project mutation | Yes |
| 2021.1 destructive | Destructive project mutation | `tests/destructive/test_2021_1_project_mutation_sandbox.py::test_2021_object_create_setnotes_delete_readbacks_against_copied_sandbox` | Creates, updates notes, reads back, deletes, and cleans up objects in a copied 2021.1 sandbox | Yes |
| 2021.1 destructive | Destructive undo | `tests/destructive/test_2021_1_project_mutation_sandbox.py::test_2021_undo_begin_end_group_records_supported_group_behavior_without_undo_uri` | Records supported 2021.1 undo group behavior without relying on an unsupported undo URI | Yes |
| 2021.1 destructive | Destructive audio import | `tests/destructive/test_2021_1_soundbank_audio_sandbox.py::test_2021_audio_import_generated_wav_readback_cleanup_against_copied_sandbox` | Imports generated audio, verifies readback, and cleans up in the copied 2021.1 sandbox | Yes |
| 2021.1 destructive | Destructive soundbank | `tests/destructive/test_2021_1_soundbank_audio_sandbox.py::test_2021_soundbank_inclusions_replace_read_remove_cleanup_against_copied_sandbox` | Replaces, reads, removes, and cleans up SoundBank inclusions in the copied 2021.1 sandbox | Yes |
| 2021.1 destructive | Destructive SwitchContainer | `tests/destructive/test_2021_1_switchcontainer_assignment_sandbox.py::test_2021_switchcontainer_assignment_add_remove_readback_cleanup_against_copied_sandbox` | Adds and removes SwitchContainer assignments with readback and cleanup in the copied 2021.1 sandbox | Yes |
| 2022.1 live | Live prerequisite | `tests/live/test_2022_live_prerequisites.py::test_2022_live_environment_prerequisites_fail_fast` | Confirms the exact 2022.1 live WwiseConsole and immutable `tests/_org/2022.1/SampleProject.wproj` prerequisites before matrix work | Yes |
| 2022.1 live | Live reflection | `tests/live/test_2022_reflection_inventory.py::test_2022_live_reflection_inventory_runs_against_sandbox` | Runs 2022.1 reflection inventory against a copied sandbox of the committed fixture and records versioned manifest evidence | Yes |
| 2022.1 live | Live WAQL | `tests/live/test_2022_waql_live_matrix.py::test_2022_live_waql_object_get_matrix_runs_read_only_against_sandbox` | Exercises read-only 2022.1 WAQL object get behavior against the copied fixture sandbox | Yes |
| 2022.1 destructive | Destructive project mutation | `tests/destructive/test_2022_project_mutation_sandbox.py::test_2022_object_create_set_delete_readbacks_against_per_test_sandbox` | Creates, sets, deletes, reads back, and cleans up objects in a per-test 2022.1 sandbox | Yes |
| 2022.1 destructive | Destructive undo | `tests/destructive/test_2022_project_mutation_sandbox.py::test_2022_undo_group_rolls_back_created_object_in_per_test_sandbox` | Verifies 2022.1 undo group rollback behavior in a per-test sandbox | Yes |
| 2022.1 destructive | Destructive audio import | `tests/destructive/test_2022_soundbank_audio_sandbox.py::test_2022_audio_import_generated_wav_readback_cleanup` | Imports generated audio, verifies readback, and cleans up in a 2022.1 sandbox | Yes |
| 2022.1 destructive | Destructive soundbank | `tests/destructive/test_2022_soundbank_audio_sandbox.py::test_2022_soundbank_inclusions_replace_read_remove_cleanup` | Replaces, reads, removes, and cleans up SoundBank inclusions in a 2022.1 sandbox | Yes |
| 2022.1 destructive | Destructive SwitchContainer | `tests/destructive/test_2022_switchcontainer_assignment_sandbox.py::test_2022_switchcontainer_assignment_add_get_remove_uses_copied_sandbox_fixture` | Adds, gets, removes, and cleans up SwitchContainer assignments in a copied 2022.1 sandbox fixture | Yes |
| 2023.1 live | Live reflection | `tests/live/test_2023_reflection_inventory.py::test_2023_live_reflection_inventory_runs_against_sandbox` | Runs 2023.1 reflection inventory against the sandbox and records versioned evidence | Yes |
| 2023.1 live | Live WAQL | `tests/live/test_2023_waql_live_matrix.py::test_2023_live_waql_object_get_matrix_runs_read_only_against_sandbox` | Exercises read-only 2023.1 WAQL object get behavior against the sandbox | Yes |
| 2023.1 destructive | Destructive project mutation | `tests/destructive/test_2023_project_mutation_sandbox.py::test_2023_object_create_set_delete_readbacks_against_per_test_sandbox` | Creates, sets, deletes, reads back, and cleans up objects in a per-test 2023.1 sandbox | Yes |
| 2023.1 destructive | Destructive undo | `tests/destructive/test_2023_project_mutation_sandbox.py::test_2023_undo_group_rolls_back_created_object_in_per_test_sandbox` | Verifies 2023.1 undo group rollback behavior in a per-test sandbox | Yes |
| 2023.1 destructive | Destructive audio import | `tests/destructive/test_2023_soundbank_audio_sandbox.py::test_2023_audio_import_generated_wav_readback_cleanup` | Imports generated audio, verifies readback, and cleans up in a 2023.1 sandbox | Yes |
| 2023.1 destructive | Destructive soundbank | `tests/destructive/test_2023_soundbank_audio_sandbox.py::test_2023_soundbank_inclusions_replace_read_remove_cleanup` | Replaces, reads, removes, and cleans up SoundBank inclusions in a 2023.1 sandbox | Yes |
| 2023.1 destructive | Destructive SwitchContainer | `tests/destructive/test_2023_switchcontainer_assignment_sandbox.py::test_2023_switchcontainer_assignment_add_get_remove_uses_copied_sandbox_fixture` | Adds, gets, removes, and cleans up SwitchContainer assignments in a copied 2023.1 sandbox fixture | Yes |
| 2024.1 live | Live reflection | `tests/live/test_2024_reflection_inventory.py::test_2024_live_reflection_inventory_runs_against_sandbox` | Runs 2024.1 reflection inventory against the sandbox and records versioned evidence | Yes |
| 2024.1 live | Live WAQL | `tests/live/test_2024_waql_live_matrix.py::test_2024_live_waql_object_get_matrix_runs_read_only_against_sandbox` | Exercises read-only 2024.1 WAQL object get behavior against the sandbox | Yes |
| 2024.1 live | Live topics | `tests/live/test_2024_object_topics_sandbox.py::test_2024_1_live_safe_object_topics_against_sandbox` | Checks safe object topic behavior in a 2024.1 sandbox without project mutation | Yes |
| 2024.1 destructive | Destructive project mutation | `tests/destructive/test_2024_project_mutation_sandbox.py::test_2024_object_create_set_delete_readbacks_against_per_test_sandbox` | Creates, sets, deletes, reads back, and cleans up objects in a per-test 2024.1 sandbox | Yes |
| 2024.1 destructive | Destructive undo | `tests/destructive/test_2024_project_mutation_sandbox.py::test_2024_undo_group_rolls_back_created_object_in_per_test_sandbox` | Verifies 2024.1 undo group rollback behavior in a per-test sandbox | Yes |
| 2024.1 destructive | Destructive audio import | `tests/destructive/test_2024_soundbank_audio_sandbox.py::test_2024_audio_import_generated_wav_readback_cleanup` | Imports generated audio, verifies readback, and cleans up in a 2024.1 sandbox | Yes |
| 2024.1 destructive | Destructive soundbank | `tests/destructive/test_2024_soundbank_audio_sandbox.py::test_2024_soundbank_inclusions_replace_read_remove_cleanup` | Replaces, reads, removes, and cleans up SoundBank inclusions in a 2024.1 sandbox | Yes |
| 2024.1 destructive | Destructive SwitchContainer | `tests/destructive/test_2024_switchcontainer_assignment_sandbox.py::test_2024_switchcontainer_assignment_add_get_remove_uses_copied_sandbox_fixture` | Adds, gets, removes, and cleans up SwitchContainer assignments in a copied 2024.1 sandbox fixture | Yes |
| 2025.1 live | Live reflection | `tests/live/test_2025_1_reflection_inventory.py::test_2025_live_reflection_inventory_runs_against_sandbox` | Runs 2025.1 reflection inventory against the sandbox and records versioned evidence | Yes |
| 2025.1 live | Live WAQL | `tests/live/test_2025_1_waql_live_matrix.py::test_2025_live_waql_object_get_matrix_runs_read_only_against_sandbox` | Exercises read-only 2025.1 WAQL object get behavior against the sandbox | Yes |
| 2025.1 live | Live topics | `tests/live/test_2025_1_object_topics_sandbox.py::test_2025_1_live_safe_object_topics_against_sandbox` | Checks safe object topic behavior in a 2025.1 sandbox without project mutation | Yes |
| 2025.1 destructive | Destructive project mutation | `tests/destructive/test_2025_1_project_mutation_sandbox.py::test_2025_object_create_set_delete_readbacks_against_per_test_sandbox` | Creates, sets, deletes, reads back, and cleans up objects in a per-test 2025.1 sandbox | Yes |
| 2025.1 destructive | Destructive undo | `tests/destructive/test_2025_1_project_mutation_sandbox.py::test_2025_undo_group_rolls_back_created_object_in_per_test_sandbox` | Verifies 2025.1 undo group rollback behavior in a per-test sandbox | Yes |
| 2025.1 destructive | Destructive audio import | `tests/destructive/test_2025_1_soundbank_audio_sandbox.py::test_2025_audio_import_generated_wav_readback_cleanup` | Imports generated audio, verifies readback, and cleans up in a 2025.1 sandbox | Yes |
| 2025.1 destructive | Destructive soundbank | `tests/destructive/test_2025_1_soundbank_audio_sandbox.py::test_2025_soundbank_inclusions_replace_read_remove_cleanup` | Replaces, reads, removes, and cleans up SoundBank inclusions in a 2025.1 sandbox | Yes |
| 2025.1 destructive | Destructive SwitchContainer | `tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py::test_2025_switchcontainer_assignment_add_get_remove_uses_copied_sandbox_fixture` | Adds, gets, removes, and cleans up SwitchContainer assignments in a copied 2025.1 sandbox fixture | Yes |
| All five versions live | Packaged gateway reads, 5 version-scoped invocations | `tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox` | Exercises packaged status, metadata, object query, buses, selection/headless boundary, and reviewed reflection routes against each real version; records Wwise readiness, whole gateway matrix, and representative command timings | Yes |
| All five versions destructive | Packaged object transactions, 5 version-scoped invocations | `tests/destructive/test_gateway_transaction_matrix.py::test_gateway_transaction_object_lifecycle_across_selected_version` | Exercises closed object lifecycle transactions with preview, confirmation, execution, verification, and cleanup in each version | Yes |
| All five versions destructive | Packaged bounded topic, 5 version-scoped invocations | `tests/destructive/test_gateway_transaction_matrix.py::test_gateway_wait_topic_matches_runner_owned_object_create_and_unsubscribes` | Waits for `object.created`, validates the version-specific raw payload, correlates its GUID to the runner-owned create, unsubscribes, and deletes the probe | Yes |
| All five versions destructive | Packaged workflow transactions, 5 version-scoped invocations | `tests/destructive/test_gateway_workflow_transaction_matrix.py::test_closed_gateway_workflows_across_selected_version` | Exercises closed audio import, SoundBank inclusion, and SwitchContainer assignment workflows with readback and cleanup | Yes |

## Live test files outside the focused matrix

| Scope | Type | Files / Nodes | What it verifies | Real Wwise required |
| --- | --- | --- | --- | --- |
| Generic live prerequisites and markers | Live prerequisite | `tests/live/test_live_marker.py`, `tests/live/test_live_prerequisites.py` | Marker opt-in and fail-fast live prerequisite behavior | Yes when executed |
| Generic headless launch | Live smoke | `tests/live/test_headless_wwise.py`, `tests/live/test_headless_timeout_cleanup.py` | Headless Wwise startup, WAAPI readiness, cleanup, and controlled timeout cleanup | Yes |
| Generic sandbox launch | Live sandbox | `tests/live/test_sandbox_fixture_live.py`, `tests/live/test_reflection_inventory.py` | Sandbox-only launch and reflection against a sample project when available | Yes |
| Generic read-only behavior | Live read-only | `tests/live/test_waql_live_matrix.py`, `tests/live/test_object_topics_sandbox.py` | Read-only WAQL object get and deterministic object topic behavior in a sandbox | Yes |
| Profiler, transport, SoundEngine | Live feasibility | `tests/live/test_profiler_transport_soundengine.py` | Profiler-backed transport and SoundEngine smoke evidence or explicit blockers | Yes |
| Subscription smoke | Live topic smoke | `tests/live/test_subscriptions_smoke.py` | Deterministic live subscription event source behavior | Yes |
| Version prerequisite files | Live prerequisite and unit-style checks | `tests/live/test_2021_1_live_prerequisites.py`, `tests/live/test_2022_live_prerequisites.py`, `tests/live/test_2023_live_prerequisites.py`, `tests/live/test_2024_live_prerequisites.py`, `tests/live/test_2025_1_live_prerequisites.py` | Exact version gates, path mismatch handling, active gate failures, and live opt-in behavior. Some tests are prerequisite-only and do not launch Wwise | Mixed, only live-marked execution requires Wwise |
| Version reflection and WAQL helpers | Live plus prerequisite-only checks | `tests/live/test_2021_1_reflection_prerequisites.py`, `tests/live/test_2021_1_object_get_matrix.py`, `tests/live/test_2022_reflection_inventory.py`, `tests/live/test_2022_waql_live_matrix.py`, `tests/live/test_2023_reflection_inventory.py`, `tests/live/test_2023_waql_live_matrix.py`, `tests/live/test_2024_reflection_inventory.py`, `tests/live/test_2024_waql_live_matrix.py`, `tests/live/test_2025_1_reflection_inventory.py`, `tests/live/test_2025_1_waql_live_matrix.py` | Version display parsing, reflection inventory, resource generation, and read-only WAQL object get behavior | Mixed, live-marked execution requires Wwise |
| Version object topics | Live topics | `tests/live/test_2021_1_object_topics_sandbox.py`, `tests/live/test_2024_object_topics_sandbox.py`, `tests/live/test_2025_1_object_topics_sandbox.py` | Safe object topic behavior for versions included in the focused matrix | Yes |

## Destructive test files outside the focused matrix

| Scope | Type | Files / Nodes | What it verifies | Real Wwise required |
| --- | --- | --- | --- | --- |
| Destructive opt-in and guard contracts | Destructive marker and prerequisite-only | `tests/destructive/test_destructive_marker.py`, `tests/destructive/test_destructive_project_guard.py` | Destructive marker opt-in, copied sandbox guard rails, and failure rather than skip for wrapped active runtime errors | Mixed, guard-only tests do not require Wwise unless active destructive execution is selected |
| Generic object mutation | Destructive sandbox | `tests/destructive/test_project_mutation_sandbox.py` | Object create, set, delete, undo group, and SwitchContainer assignment or exact blocker recording | Yes |
| Generic soundbank and audio | Destructive sandbox | `tests/destructive/test_soundbank_audio_sandbox.py` | Audio import, tab-delimited import, imported topics, SoundBank inclusions, generation, and process definition evidence or blockers | Yes |
| Generic core object deferred cases | Destructive sandbox | `tests/destructive/test_object_deferred_sandbox.py` | Reopened core object function and topic cases with readable postconditions or exact blockers | Yes |
| Generic SwitchContainer assignment | Destructive sandbox | `tests/destructive/test_switchcontainer_assignment_sandbox.py` | Assignment add, get, remove, topic identity payloads, readback pairs, and cleanup | Yes |
| Versioned destructive matrix files | Destructive sandbox | `tests/destructive/test_2021_1_*_sandbox.py`, `tests/destructive/test_2022_*_sandbox.py`, `tests/destructive/test_2023_*_sandbox.py`, `tests/destructive/test_2024_*_sandbox.py`, `tests/destructive/test_2025_1_*_sandbox.py` | Version-specific project mutation, undo, audio import, SoundBank inclusion, and SwitchContainer assignment behavior in copied or per-test sandboxes | Yes |

## Unit and contract test groups

| Scope | Type | Files / Nodes | What it verifies | Real Wwise required |
| --- | --- | --- | --- | --- |
| Five-version public execution contract | Unit and fake gateway | `tests/unit/test_public_route_coverage_contract.py`, `tests/unit/test_public_route_program_matrix.py`, `tests/unit/test_public_route_negative_contracts.py`, `tests/unit/test_io_policy.py`, `tests/unit/test_transaction_cleanup.py`, optional `tests/unit/test_public_route_registry_integrity.py`, and focused nodes from `tests/unit/test_transaction_gateway.py` | Exact 808-row manifest-minus-exclusions coverage, schema-driven fake dispatch/subscription, hard-boundary rejection, isolated path confinement, same-connection Undo, lifecycle cleanup binding, and generic transaction lifecycles without network or real processes | No |
| Authoring UI overlay and transactions | Unit, resource, and fake gateway | `tests/unit/test_authoring_ui_commands_collector.py`, `tests/unit/test_authoring_ui_commands_manifest.py`, `tests/unit/test_authoring_ui_profile.py`, `tests/unit/test_operation_ui_commands.py`, `tests/unit/test_operation_ui_commands_registry.py`, `tests/unit/test_authoring_ui_gateway.py` | Overlay digest/counts, offline `--profile`, automatic live host selection, WwiseConsole zero-business-dispatch boundaries, 2025 file proof/rebinding, exact platform mapping, register/unregister inventory membership, and unregister XOR modes through fake clients. This is not live GUI/project-effect evidence. | No |
| Plug-in creation and RTPC/platform editing | Unit and fake readback | `tests/unit/test_operation_plugin.py`, `tests/unit/test_operation_plugin_registry.py`, `tests/unit/test_operation_platform_rtpc.py`, and the focused plug-in full-chain node in `tests/unit/test_transaction_gateway.py` | Closed Source/Effect creation, typed property metadata, notes/language/platform readback view, Wwise 2022 fixed Effect-reference binding, Wwise 2023+ new EffectSlot binding, complete fake transaction chain, platform link/edit contracts, and exact 128-row RTPC add/update capacity behavior. This is not a new live plug-in or RTPC mutation result. | No |
| Debug/Lua full transaction boundaries | Unit and fake gateway | `tests/unit/test_debug_lua_operations.py`, `tests/unit/test_debug_lua_gateway_full_chain.py`, focused debug nodes from `tests/unit/test_transaction_gateway.py` | Closed Lua source/file proofs, debug mode result-schema boundaries, and restart/assert/crash single-dispatch terminal-indeterminate/replay blocking through fake clients | No |
| Dispatcher and routing | Unit | `tests/unit/test_dispatcher.py`, `tests/unit/test_dispatch_routes_all_2022.py`, `tests/unit/test_package_placeholders.py` | Dispatcher validation, fake runtime routing, error shape, destructive dry-run blocking, topic dispatch, placeholder package behavior | No |
| Headless lifecycle internals | Unit | `tests/unit/test_headless_lifecycle.py` | Path resolution, dynamic port launch, argument handling, readiness, timeout cleanup, shutdown, process group cleanup, and Windows force-kill branches using fakes | No |
| Live and destructive safety gates | Unit and prerequisite-only | `tests/unit/test_live_environment_contract.py`, `tests/unit/test_active_gate_failures.py`, `tests/unit/test_sandbox_fixture.py`, `tests/unit/test_2021_1_live_environment_contract.py`, `tests/unit/test_2023_live_environment_contract.py`, `tests/unit/test_2024_live_environment_contract.py`, `tests/unit/test_2025_1_live_environment_contract.py`, `tests/unit/test_2021_1_destructive_safety.py`, `tests/unit/test_2023_destructive_safety.py`, `tests/unit/test_2024_destructive_safety.py`, `tests/unit/test_2025_1_destructive_safety.py` | Exact Wwise paths, strict real skip-to-failure conversion, sandbox source immutability, destructive target guards, audit write behavior, and unsafe sandbox rejection | No |
| Manifest resources and coverage accounting | Unit | `tests/unit/test_manifest_store.py`, `tests/unit/test_manifest_determinism.py`, `tests/unit/test_api_coverage_audit.py`, `tests/unit/test_no_silent_skips.py`, `tests/unit/test_2021_1_api_resource_coverage.py`, `tests/unit/test_2022_api_resource_coverage.py`, `tests/unit/test_2023_api_resource_coverage.py`, `tests/unit/test_2024_api_resource_coverage.py`, `tests/unit/test_2025_1_api_resource_coverage.py`, `tests/unit/test_2025_1_added_api_classification.py` | Manifest loading, deterministic serialization, schema shape, coverage status accounting, deferred or implemented coverage, and versioned API resources | No |
| Native request-surface and metadata indexes | Unit and fake gateway | `tests/unit/test_public_route_registry_integrity.py`, `tests/unit/test_object_native_surface.py`, `tests/unit/test_metadata_catalog.py`, `tests/unit/test_metadata_session_cache.py`, `tests/unit/test_metadata_discovery.py`, `tests/unit/test_metadata_discovery_gateway.py`, `tests/unit/test_semantic_builder_metadata.py`, and focused metadata nodes in `tests/unit/test_waapi_gateway.py` | Complete five-version Function-route partition; high-risk reflected-selector mapping; object/import normalized-equivalent coverage; exact object-type catalog provenance; bounded live property/reference discovery without object-specific aliases; bounded display/UI-detail fallback scans; same-object dependency closure; session/project/runtime-bound metadata caching and discovery-to-preview reuse; durable canonical-GUID but wrapper-local mutable path/name scopes; dynamic-state cache exclusions; corruption, symlink, capacity, and fallback boundaries | No |
| Version isolation and contracts | Unit | `tests/unit/test_2021_1_version_contract.py`, `tests/unit/test_2023_version_contract.py`, `tests/unit/test_2024_version_contract.py`, `tests/unit/test_2025_1_version_contract.py`, `tests/unit/test_2023_version_isolation.py`, `tests/unit/test_2025_1_version_isolation.py`, `tests/unit/test_2023_cross_version_audit.py`, `tests/unit/test_2024_cross_version_audit.py`, `tests/unit/test_2025_1_cross_version_audit.py` | Canonical version names, default dispatcher version stability, no fallback to older or bare versions, and cross-version resource isolation | No |
| Deferred registries and live coverage matrices | Unit | `tests/unit/test_deferred_registry.py`, `tests/unit/test_2021_1_deferred_registry.py`, `tests/unit/test_2023_deferred_registry.py`, `tests/unit/test_2024_deferred_registry.py`, `tests/unit/test_2025_1_deferred_registry.py`, `tests/unit/test_live_coverage_matrix.py`, `tests/unit/test_2023_live_coverage_matrix.py`, `tests/unit/test_2024_live_coverage_matrix.py`, `tests/unit/test_2025_1_live_coverage_matrix.py`, `tests/unit/test_phase2_coverage_statuses.py`, `tests/unit/test_phase2_coverage_summary.py`, `tests/unit/test_phase21_uri_policy.py`, `tests/unit/test_wrapper_only_categories.py` | Deferred evidence shape, live coverage status rules, policy categories, phase summary accounting, exact reopened URI lists, and non-overclaiming constraints | No |
| Semantic builders | Unit | `tests/unit/test_semantic_builder_*.py`, `tests/unit/test_2021_1_semantic_builders.py`, `tests/unit/test_2023_semantic_builders.py`, `tests/unit/test_2023_semantic_source_notes.py`, `tests/unit/test_semantic_builder_source_notes.py`, `tests/unit/test_semantic_builder_audit.py` | Structured query compilation, identity, metadata, property, object mutation, SoundBank, SwitchContainer, schema validation, source note gates, and versioned builder grounding. Audio import is covered by the formal transaction-operation tests rather than a parallel preview-only builder. | No |
| WAQL, structured-query, and bounded advanced-query helpers | Unit and fake gateway | `tests/unit/test_waql_docs_gate.py`, `tests/unit/test_waql_examples.py`, `tests/unit/test_waql_live_matrix.py`, `tests/unit/test_2021_1_waql_matrix.py`, `tests/unit/test_2023_waql_mutation_guard.py`, `tests/unit/test_2024_waql_mutation_guard.py`, `tests/unit/test_structured_waql_builder.py`, and focused query nodes in `tests/unit/test_waapi_gateway.py` | Historical WAQL resource gates and live-matrix shapes; versioned `waapi-skill.object-query/v1` compiler parity; separately disclosed `waapi-skill.advanced-object-query/v1`; fixed read-only URI, exact request ownership, UTF-8 input ceilings, trimmed single-line framing with no comments/semicolons/unclosed string-or-regex literals, complex return expressions, final cap, strict result shape, no-retry errors, and explicit absence of a mutation-identity bridge. Program success proves the Python/Gateway boundary, not real-Wwise acceptance of native advanced syntax. | No |
| Fixture inventory and source layout | Unit | `tests/unit/test_org_fixture_source.py`, `tests/unit/test_2023_fixture_source.py`, `tests/unit/test_2024_fixture_inventory.py`, `tests/unit/test_2025_1_fixture_inventory.py`, `tests/unit/test_skill_layout.py`, `tests/unit/test_skill_scaffold.py`, `tests/unit/test_skill_md.py`, `tests/unit/test_skill_contract.py` | Authored fixture manifests and hashes, no generated artifacts, canonical skill layout, scaffold, and skill contract documentation | No |
| Packaged docs and semantic-definition contracts | Unit | `tests/semantic/test_codex_eval_bundle_v3.py`, `tests/semantic/test_docs_semantic_inventory.py`, `tests/unit/test_2021_1_reference_layout.py`, `tests/unit/test_2023_reference_layout.py`, `tests/unit/test_2024_reference_layout.py`, `tests/unit/test_2025_1_reference_layout.py`, `tests/unit/test_skill_layout.py`, `tests/unit/test_skill_contract_protocol.py`, `tests/unit/test_windows_gate.py`, `tests/unit/test_platform_paths.py`, `tests/unit/test_run_help.py`, `tests/unit/test_script_helpers.py` | V3 five-version unique-API prompt/oracle coverage, online/offline separation, request-mapping blockers, fresh Codex documentation, packaged reference layout, Skill protocol, Windows evidence gate, platform paths, and script helpers | No |
| Integration workflow contracts | Unit and fake runtime | `tests/semantic/test_codex_integration_workflows.py`, `tests/semantic/test_codex_integration_profile_cli_wiring.py`, `tests/semantic/test_codex_integration_workflows_v2.py`, `tests/semantic/test_codex_integration_profile_wiring_v2.py`, `tests/semantic/test_codex_integration_harness_v2.py`, `tests/semantic/test_codex_integration_original_paths_v2.py`, `tests/semantic/test_codex_integration_rifle_runtime_v2.py`, `tests/semantic/test_codex_integration_footsteps_runtime_v2.py`, `tests/semantic/test_codex_integration_weapons_runtime_v2.py`, `tests/unit/test_collect_integration_workflows_v2_baseline.py` | Public 12-task composition and default-suite CLI wiring; legacy component provenance; fixed-baseline topology and manifests only for Rifle, Footsteps, and Weapons; prompt and Broker protocol; original-path binding; business oracles; sandbox/source immutability; cleanup/quarantine; and symlink-safe baseline maintenance without starting Codex or Wwise | No |
| Feasibility and plan resources | Unit | `tests/unit/test_profiler_soundengine_feasibility.py`, `tests/unit/test_mutating_live_plan.py`, `tests/unit/test_core_object_deferred_plan.py`, `tests/unit/test_soundbank_audio_live_plan.py`, `tests/unit/test_soundbank_process_definition_plan.py`, `tests/unit/test_switchcontainer_assignment_plan.py`, `tests/unit/test_topic_live_plan.py` | Planned live or destructive cases, required evidence contracts, blocker rules, cleanup expectations, and promotion limits. These are plan/resource tests, not live behavior proof | No |
| Subscription runtime | Unit | `tests/unit/test_subscriptions.py` | Sequential executor guidance, subscription cleanup handles, bounded queues, background listener cleanup, callback error handling, and clientless registry behavior | No |

## Collection notes

| Command | Result | Notes |
| --- | --- | --- |
| `ci/test.sh --mode program -- -q -ra` on exact candidate `1eeabb9878f18c554bdbd70f940f805e31b70570` | 3646 passed, 2 skipped; exit 0 | Final #78 five-version deterministic gate. All 17 `object.create`, `object.createPlugin`, `object.set`, and `object.setRTPC` lanes use `object-graph-business/v1`; opaque object/field/type/control-input/output-bus handles and stable business fields compile native paths, types, metadata scopes/tokens, dependency order, batches, revisions, requests, and one Preview continuation inside the Gateway. The old object Composer and fallback are absent. The gate starts neither Codex nor Wwise; the two skips are the native-Windows encoded-shell proof and NTFS junction behavior on macOS. |
| `ci/test.sh --mode nonlive -- -q tests/semantic/test_codex_operation_draft_archive_v3.py tests/semantic/test_codex_prompt_provenance_v3.py tests/unit/test_operation_draft_seal.py tests/unit/test_single_typed_input_cutover.py tests/unit/test_typed_query_construction.py tests/unit/test_typed_topic_construction.py tests/unit/test_operation_verification_kind_ownership.py` | 175 passed, 0 skipped; exit 0 | Focused release regression for current typed evidence, historical archive/provenance replay, old-state recreation, the single-input cutover, Query/Topic construction, and verifier-strength ownership. No Codex, Wwise, live, or destructive body ran. |
| `ci\test.bat --mode program -- -q -ra` | 2609 passed, 34 skipped in 167.50s; exit 0 | Native-Windows program gate for exact candidate `7f54506783a131695bafb97b89103488cb73d96c`. The batch launcher delegated repository development tests to Poetry; it did not use global Python or the Skill-local runtime environment, and it started neither Codex nor Wwise. This frozen result predates the current Composer candidate and is not a count comparison with the macOS row above. |
| `ci\test.bat --mode program -- -q -ra` | 3322 passed, 15 skipped; exit 0 | Native-Windows program gate for exact typed-input candidate `283d6199a3fa11ea06de38dd7971450c0445dce4`. The 15 skips were POSIX/Wine-only SIGINT, filesystem-mode, hard-link, virtual-drive, localization, and SoundBank cases; no native-Windows program node that should run was skipped. The batch launcher delegated to Poetry and started neither Codex nor Wwise. |
| Native-Windows #48 focused command over batch/shell parity, category evidence, platform command/process/filesystem, filesystem security, host paths, Draft/transaction stores, SoundBank paths, semantic host/filesystem/path-budget tests, and four native PowerShell Broker transport nodes | 442 passed, 7 skipped; exit 0 | Exact harness candidate `412a23b55822a70da2b26ec76971b23cf87bd9e8`, run through `ci\test.bat --mode nonlive -- -q -ra ...`. The seven skips were POSIX shell/mode/hard-link cases. Native cmd parity, junction/reparse behavior, Windows lock/CAS, path budgets, isolated filesystem handling, and PowerShell Core transport all ran. The current public typed proof followed `operation-schema` through dynamic container disclosure and Draft facts, preserving hostile scalar and nested array/object values exactly through pwsh -> PS1 -> authenticated Broker -> packaged Gateway materialization. The older raw-JSON preservation nodes remain transport regression only and receive no current product-path credit. `pwsh` was 7.6.4 with native argument passing mode `Windows`; no global dependency, PATH, or PowerShell setting changed. |
| `ci/test.sh --mode nonlive -- -q -ra` on exact candidate `1eeabb9878f18c554bdbd70f940f805e31b70570` | 8620 passed, 110 skipped, 27 deselected; exit 0 | Final #78 broad regression after archiving the pre-cutover object Composer protocols. It covers the five-version object graph compiler, public continuation completeness, field/type discovery, list parity, plug-in and RTPC validation, stale/repair/hostile/non-bypass cases, immutable Preview and verifier boundaries, interface-depth generation, historical replay, and cross-platform Fresh harness. No Codex, Wwise, live, or destructive body ran; declared platform/live/evidence skips receive no PASS credit. |
| Final #77 Program gates on exact candidate `96dc3f284d842e15b820da3e3fdfd69f38f190d7` | macOS `3728 passed, 2 skipped`; native Windows `3715 passed, 15 skipped`; both exit 0 | Fixed five-version deterministic gate for the 13 `object.setProperty`, `object.setReference`, and `object.setLinked` business-declaration lanes, including live-bound field handles, repair/stale/scope/value negatives, exact staged continuation, removal of normal `inline_typed` ingress and compact-catalog native fields, inventory closure, and existing safety/verifier regressions. Platform skips remain the declared native-Windows or POSIX-only cases and receive no borrowed credit. |
| `ci/test.sh --mode nonlive -- -q -ra` on exact candidate `96dc3f284d842e15b820da3e3fdfd69f38f190d7` | 8793 passed, 107 skipped, 27 deselected; exit 0 | Final #77 broad regression. It includes Program, archive/replay, campaign evidence validation, the shared Business Agent profile seam, Alarm integration migrated to staged object-metadata Draft composition, compact operation-catalog non-leakage, documentation and interface-depth inventory. No live or destructive body, Codex task, or Wwise process ran; declared skips receive no PASS credit. |
| `run_codex_skill_campaign.py --profile object_metadata_business_1 --model gpt-5.6-terra --reasoning-effort medium --service-tier default` on exact candidate `96dc3f284d842e15b820da3e3fdfd69f38f190d7` | macOS root `imac-object-metadata-96dc3f2-r6`: 1 passed / 0 failed plus identical verify-only; native-Windows strict root `iwin-object-metadata-96dc3f2-r6-strict`: 1 passed / 0 failed plus identical verify-only | Final current-v3 Fresh Alarm reference-repair proof after compact `operations` stopped exposing legacy `property` / `reference` arguments. Both Agents selected `object.setReference`, used user path segments and UI meaning `Output Bus`, copied only object/field handles, followed the Gateway-owned staged continuation, reached one GUID-bound immutable Preview, and executed nothing. Windows attested a user-owned `console` row and `explorer.exe` in the same session, exported `InteractiveToken`, reported `Limited`, deleted the temporary task, and had no scoped residual in an independent SSH process check; verify-only started neither Codex nor Wwise. The earlier final-harness Windows root `iwin-object-metadata-6af699e-r4-interactive` selected broad `object.set`, was rejected by the authenticated Broker on command 1, and remains a frozen 0/1 semantic-failure root without mutation or verify-only. Earlier macOS r1-r3 and Windows r1-r2 failure roots likewise remain frozen. |
| `run_codex_skill_campaign.py --profile object_graph_business_1 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --max-pre-action-retries 0` on exact candidate `1eeabb9878f18c554bdbd70f940f805e31b70570` | macOS root `imac-object-graph-1eeabb9-r6`: 1 passed / 0 failed plus identical verify-only; native-Windows root `iwin-object-graph-1eeabb9-r6`: 1 passed / 0 failed plus identical verify-only | Final current-v3 Weather graph proof. Both fresh memory-off Agents supplied only the closed Actor Mixer/SFX names, infinite-loop outcomes, and `-4`/`-6 dB`; the Gateway bound the parent, derived Wwise types, paths, property metadata, graph order, native request, and one immutable Preview. Each root reconciled 8/8 Broker records and passed every no-bypass/no-execute/workspace/Skill-integrity gate; Wwise was not started. macOS used a one-shot LaunchAgent with one run and exit 0. Windows proved user `cbos` on console session 1 with `explorer.exe`, exported `InteractiveToken`, reported `Limited`, used the sealed PowerShell Core host, and ended with task result 0. Both temporary launchers were deleted and independent scoped-process checks were empty. Earlier r1-r4 blocked/semantic/hash roots remain frozen and receive no PASS credit. |
| `ci/test.sh` / `ci\test.bat --version 2022.1|2025.1 --mode destructive -- -q -ra -k object_metadata_business_draft_executes_field_verifiers` on exact transaction candidate `05e64d6939a82b60e15caf0e390b21f9a2435270` | macOS and native Windows: 2022.1 and 2025.1 each `1 passed / 11 deselected`; all four invocations exit 0 | Real #77 proof for public Business Draft → check → immutable Preview → confirm → execute-once → operation-specific readback. Every invocation changed and verified `Volume` plus `OutputBus`; 2025.1 also changed and verified platform link state. Source-project hashes/mtimes remained unchanged and sandbox cleanup completed. The later packaged change in `96dc3f2` only removes native arguments from the offline compact operation catalog; it does not alter transaction compilation, dispatch, verification, or cleanup, and has exact same-candidate Program/Non-live plus dual-host Fresh proof. |
| `ci/test.sh` / `ci\test.bat --version 2022.1|2025.1 --mode destructive -- -q -ra -k 'gateway_transaction_object_lifecycle_across_selected_version or gateway_wait_topic_matches_runner_owned_object_create_and_unsubscribes or object_graph_business_draft_executes_weather_graph_plugin_bulk_set_and_rtpc'` on exact candidate `1eeabb9878f18c554bdbd70f940f805e31b70570` | macOS and native Windows: 2022.1 and 2025.1 each `3 passed / 10 deselected`; all four invocations exit 0 | Final #78 real-host proof. The object-graph case recursively created Weather/Rain/Wind, created a Wwise Tone Generator Source plug-in, bulk-set two objects, applied and verified an RTPC curve, then deleted the root; the two adjacent cases prove legacy real fixtures now create through the same Business Draft and Topic subscription cleanup remains exact. Every retained category row records the matching Wwise build, equal source hash and tree metadata before/after, deleted sandbox, cleaned lifecycle, and zero residual processes. Authoring UI remains explicitly host-blocked on WwiseConsole and receives no credit. |
| `run_codex_skill_matrix.py --profile deep_interface_mvp_8 --model gpt-5.6-terra --reasoning-effort medium --service-tier default` on exact candidate `4b2d9aa` | macOS root `deep-interface-mvp-4b2d9aa-mac-r2-full`: 8 passed / 0 failed; native-Windows root `deep-interface-mvp-4b2d9aa-win-r1-full`: 8 passed / 0 failed; both exit 0 | Same-candidate Fresh Agent MVP acceptance for Weather, Rifle, Footsteps, and Weapons, with two paraphrases each. A preceding macOS priority root passed the three formerly failing units 3/3 before the full root; it is not counted as the full-profile result. Earlier semantic and infrastructure failure roots remain frozen without replay. Every unit used a fresh memory-disabled Terra task, the test-only Gateway connected to no Wwise process and reported no mutation, Skill/workspace integrity gates passed, macOS used a one-shot LaunchAgent, Windows used a temporary `InteractiveToken`/`Limited` Scheduled Task, and final scoped process checks were empty. |
| `run_codex_skill_campaign.py --profile audio_import_business_8 --model gpt-5.6-terra --reasoning-effort medium --service-tier default` on exact packaged-Skill candidate `4be64fd80fb14d800a8890012f65fca666ab98f4` | macOS root `imac-aib-4be64fd-r17-full`: 8 passed / 0 failed plus identical verify-only; native-Windows root `iwin-aib-4be64fd-r17-full`: 8 passed / 0 failed plus identical verify-only | Same-candidate production-Adapter Fresh Agent acceptance for two Weather, two Rifle, two Footsteps, and two custom-field Weapons prompts. Each fresh memory-off Terra task stopped at immutable Preview; no Wwise process or project mutation was permitted. The Agent supplied ordered user path segments while Gateway owned separators, Wwise types, metadata scopes, dependency order, batching, native rows, and copy-ready continuations. All ten sealed files per host matched their hashes, scoped process checks were empty, and the one-shot macOS LaunchAgent and native-Windows `InteractiveToken`/`Limited` Scheduled Tasks were deleted. Earlier r15/r16 semantic failure roots remain frozen without verify-only replay. |
| `run_codex_skill_campaign.py --profile audio_import_business_8 --model gpt-5.6-terra --reasoning-effort medium --service-tier default` on packaged-Skill candidate `9a4de1624bc11d24fe38b2e740b5a92cca3d271e` with semantic harness `3ebbf5fab24feacc5d3bf5adf2eddb2c949057e4` | macOS root `imac-aib-9a4de16-h3ebbf5f-r21-full`: 8 passed / 0 failed plus identical verify-only; native-Windows root `iwin-aib-9a4de16-h3ebbf5f-r22-full`: 8 passed / 0 failed plus identical verify-only; Windows priority root `iwin-aib-9a4de16-h3ebbf5f-r21-rifle-a`: 1 passed / 0 failed | Final review-repaired Fresh Agent acceptance after removing unscoped mutation names and batching exact-ID revalidation. The harness accepts either omission of compiler-derived SFX language or one explicit exact `language=SFX`, while rejecting duplication, contradiction, or any other language. Earlier macOS r18 and Windows r18-r20 failure roots remain frozen without verify-only: failures stopped before Preview because of a local shell start miss, corrupted Broker authority, or the superseded omission-only semantic rule. Every full unit used a fresh memory-off Terra task and stopped at Preview without Wwise or mutation. The one-shot macOS LaunchAgent and native-Windows `InteractiveToken`/`Limited` Scheduled Tasks were deleted; scoped process checks were empty. |
| `run_codex_skill_matrix.py --profile object_lifecycle_business_3 --model gpt-5.6-terra --reasoning-effort medium --service-tier default` | Packaged Skill `853f115`: macOS root `imac-obl-853f115-v3-r2` 3 passed / 0 failed; native-Windows root `iwin-obl-853f115-v3-r2` 2 passed / 1 infrastructure/trace failure, then `iwin-obl-853f115-v3-r3-rename` 1 passed / 0 failed. Final shared-harness candidate `ec4eee5`: macOS `imac-obl-ec4eee5-v3-r5-rename` and Windows `iwin-obl-ec4eee5-v3-r5-rename` each 1 passed / 0 failed. | Current-v3 Fresh routing proof for notes, delete, and rename: natural Wwise paths crossed the Agent boundary, Business Draft bound exact live GUIDs, Gateway created immutable Preview, and all PASS roots had exact Broker reconciliation, no direct WAAPI/inline Python, no execute, unchanged Skill/workspace, and zero scoped residual processes. Native Windows used the active desktop user through temporary `InteractiveToken`/`Limited` Scheduled Tasks. The failed r2 rename had one pre-Broker `CreateProcessAsUserW 267` attempt followed by a successful Agent retry and therefore received no PASS; earlier semantic/fixture roots also remain frozen. The final neutral shared runner/fixture seam was re-proved on both hosts without Wwise or mutation. |
| Object-lifecycle Business Draft real-Wwise test on exact packaged-Skill candidate `2f2be21` | macOS: 2022.1 and 2025.1 PASS; native Windows: 2022.1 and 2025.1 PASS; every host/version invocation exercised copy, move, delete, rename, and notes through public Business Draft → check → immutable Preview → confirm → execute → verify. | Proportional #92 real-host evidence for all five operations and their operation-specific verifiers. Every source-project full hash and mtime remained unchanged, passing sandboxes were deleted, cleanup completed, and scoped residual-process checks were empty. Later packaged change `853f115` only removed the caller-visible Preview `--apply` transport flag; request compilation, dispatch, execution, verification, and cleanup remained unchanged and received focused Program plus current-v3 routing proof. |
| `ci/test.sh` / `ci\test.bat --version 2022.1|2025.1 --mode destructive -- -q -ra -k closed_gateway_workflows_across_selected_version` on exact candidate `6251481c1dcafb362a52f25602e6023635e581a8` | macOS: 2022.1 and 2025.1 each 1 passed / 9 deselected; native Windows: 2022.1 and 2025.1 each 1 passed / 9 deselected; every invocation exit 0 | Real-Wwise validation of the same packaged Skill tree as Fresh candidate `4be64fd`; commits through `6251481` changed only tests and the real-test Adapter. The closed business Draft created the canonical `Sound SFX` import Preview, executed once after confirmation, verified imported identity/path/notes/source evidence, and then completed the broader Gateway workflow. All four category-evidence rows record operation-specific readback PASS, identical source hash and tree metadata before/after, deleted sandbox, cleaned process lifecycle, and zero residual processes. Authoring UI is explicitly blocked because the configured host is WwiseConsole. |
| `ci/test.sh` / `ci\test.bat --version 2022.1|2025.1 --mode destructive -- -q -ra -k closed_gateway_workflows_across_selected_version` for final packaged-Skill candidate `9a4de1624bc11d24fe38b2e740b5a92cca3d271e` | macOS: 2022.1 and 2025.1 each 1 passed / 9 deselected; native Windows at harness-only Git candidate `3ebbf5fab24feacc5d3bf5adf2eddb2c949057e4`: 2022.1 and 2025.1 each 1 passed / 9 deselected; every invocation exit 0 | Post-review real-Wwise revalidation of the unchanged packaged Skill on both hosts. All four retained rows record operation-specific object-topology, scalar/reference/link, relationship, and SoundBank/file-artifact PASS; equal source hash and tree metadata before/after; deleted sandbox; cleaned lifecycle; and zero residual processes. Authoring UI remains explicitly blocked on the configured WwiseConsole hosts rather than receiving behavior credit. |
| Historical `typed_input_cross_version_25` repair roots before same-candidate acceptance | macOS: 25/25 cumulative unique PASS; native Windows: 25/25 cumulative unique PASS; final passing repair roots passed identical `--resume --verify-only` | This earlier migration evidence accumulated unique PASS across evolving frozen candidates rather than proving one common candidate. macOS contributors were r8, r10, r14-r19, r21-r25, r31, r40, r54, and final `campaign-typed-input-0093efa-macos-r57-a-typ23`; Windows contributors were r18-r20, r23-r25, r29, r35, r42, and final `campaign-typed-input-2392be4-windows-r56-a-fail2`. Every failed root was frozen without same-root retry or verify-only, source integrity remained unchanged, passing sandboxes were removed, and scoped processes were cleared. This row is historical provenance only and contributes no credit to the final same-candidate result below. |
| `run_codex_skill_campaign.py --profile typed_input_cross_version_25 ... --max-pre-action-retries 0` on exact Git candidate `c5711418229ee3b2f6a9f35a91ab5f2945ea147b` | macOS: 25/25 unique PASS across fresh roots `mc571141-typ24-generate-r1` (1) and `mc571141-rest24-r1` (24); native Windows: 25/25 unique PASS across fresh roots `wc571141-typ22-query-r1` (1) and `wc571141-rest24-r1` (24); all four roots passed identical `--resume --verify-only` | Same-candidate representative five-version Fresh Agent acceptance for zero, concise query, generic typed query/media, named Draft/inline operations, metadata, Topic, file, Lua, SoundBank, and `object.create` workflows—not every packaged API and not a single-root 25/25 claim. Every task used a fresh memory-off `gpt-5.6-terra` task at medium reasoning/default tier and `--max-pre-action-retries 0`; earlier failure roots were frozen without retry or verify-only. Native-Windows fresh runs used the active logged-in user through temporary Task Scheduler tasks with `InteractiveToken`/`Limited`; SSH only launched, waited, and read evidence. Across the 50 final-candidate PASS lifecycle records, source full hashes and project mtimes are unchanged, PASS sandboxes are removed, lifecycle errors are empty, and final scoped Codex/Wwise process counts are zero. The four replay checks started neither Codex nor Wwise. |
| `ci/test.sh --version all --mode matrix -- -q -ra -x` | macOS exact candidate `9fb8c01d31d854d975f5443cb87f35be9a232309`: Live 20 passed; Destructive 46 passed / 4 version-bound Lua skips; exit 0 | Sequential WwiseConsole builds 2021.1.14.8108, 2022.1.19.8584, 2023.1.19.8928, 2024.1.13.9056, and 2025.1.7.9143 exercised public typed Gateway continuations for object topology, scalar/reference/link, relationships, SoundBank/file artifacts, Topics, CLI/SoundEngine, and 2025 inline Lua. Operation-specific categories passed business readbacks; Lua remained result-schema-only. SoundEngine was explicitly blocked on 2021/2022 Console and result-schema-only on 2023–2025. Authoring UI was explicitly blocked on every configured Console host rather than counted as behavior coverage. Every source hash and tree-metadata/mtime digest was unchanged; all sandboxes were deleted and every launch audit reported zero residual processes. Exact category rows are sealed locally in `.waapi-skill-state/evidence/full-typed-input/macos-category-evidence.jsonl`. Deliberate assert/crash/restart routes were not executed. |
| `ci\test.bat --version <2021.1..2025.1> --mode live|destructive -- -q -ra` (ten strictly sequential invocations) | Native-Windows exact candidate `283d6199a3fa11ea06de38dd7971450c0445dce4`: Live 20 passed; Destructive 46 passed / 4 version-bound Lua skips; every invocation exit 0 | Matching WwiseConsole builds 2021.1.14.8108, 2022.1.19.8584, 2023.1.19.8928, 2024.1.13.9056, and 2025.1.7.9143 exercised the same applicable public-Gateway categories without borrowing macOS credit. Object topology, scalar/reference/link, relationship, SoundBank/file artifact, and Topic categories passed operation-specific or exact-event verification. SoundEngine was explicitly blocked as host-unavailable on 2021/2022 Console and passed result-schema-only on 2023–2025; Authoring UI was explicitly blocked on all Console hosts; 2025 Lua passed result-schema-only while the four older lanes were the recorded version skips. All ten Windows evidence rows bind the exact candidate and host build. Every source full-tree hash and metadata/mtime digest was identical before and after, every sandbox was deleted, cleanup was `cleaned`, and residual processes were empty. Evidence is retained locally in `.waapi-skill-state/evidence/full-typed-input/windows-category-evidence.jsonl`; no global dependency/PATH change, Fresh Agent, deliberate assert/crash/restart route, or source-project mutation occurred. |
| `run_codex_skill_campaign.py --profile modification_policy_9 ... --campaign-root skills/waapi-skill-workspace/campaign-modification-policy-9-c7` followed by the identical command with `--resume --verify-only` | 9 passed, 0 failed, 0 blocked, 0 indeterminate in 8m 45s | Historical Wwise 2022.1 evidence for the exact frozen c7 policy candidate: 15 user turns across nine unique memory-isolated Codex Terra threads; three repetitions each of `read_only`, question-style `ask_before_changes`, and same-turn `allow_changes`. Every read-only case had zero primary mutation dispatches; every ask/allow case had exactly one. All six writes created and verified seven objects with 46 passing business assertions per case. Source SampleProject hashes remained unchanged, all sandboxes were cleaned, and verify-only rechecked the sealed evidence without starting Codex or Wwise. It predates and does not semantically validate the current structured/advanced-query and closed-selector candidate. |
| `run_codex_skill_campaign.py --profile heavy_cross_version_80 ... --campaign-root skills/waapi-skill-workspace/h80-release-c38` followed by the identical command with `--resume --verify-only` | 80 passed, 0 failed, 0 blocked, 0 indeterminate in 1h 38m 10s | Historical sealed evidence for the exact c38 candidate only, before the current policy-aware preview/authorization migration. It used 80 fresh threads and 145 turns with memory disabled; source-project hash/mtime drift, retained sandboxes/state, residual Wwise processes, timeouts, inline Python, unexpected commands, and source-file changes were all zero. It is not a passing result for the current candidate. |
| `run_codex_skill_campaign.py --profile compound_heavy_cross_version_24 ... --campaign-root skills/waapi-skill-workspace/ch-final24-compact-v4`, then the two failed units in `ch-repair2-compact-v5` followed by identical `--resume --verify-only` | Initial 22 passed / 2 failed in 33m 31s; repair 2 passed / 0 failed in 3m 21s | Historical compound-heavy evidence for the exact frozen v4/v5 candidates used 26 fresh memory-disabled Codex Terra threads and 50 turns across Wwise 2022.1 and 2025.1. The initial failures made no mutation and were quarantined; the repair candidate passed both with real business assertions and clean lifecycle teardown. Source-project hash and mtime drift were zero in both roots. This records passing evidence for every selected unit across the initial and repair roots, not one unified 24/24 run on a single frozen candidate and not semantic validation of the current structured/advanced-query and closed-selector candidate. |
| Composer Phase 1/2 focused real evidence | `object.set`: macOS `imac-flatrow-6869724-r1` and native-Windows `i15-6869724-r1`, each 4 passed plus verify-only; `audio.import`: macOS `imac-import-6479595-r13-final6` 6 passed plus verify-only; native-Windows `iwin-import-f87b800-r2-interactive` 4 passed / 2 failed, `iwin-import-0be8266-r3-rifle-footsteps` 1 passed / 1 failed, and `iwin-import-0be8266-r4-rifle` Rifle passed plus verify-only | This is focused Adapter evidence for Weather/Weapons and Weather/Rifle/Footsteps on Wwise 2022.1/2025.1, not public `integration` acceptance. The later Windows commits changed only program/semantic tests and harness support, not the packaged Skill tree. All six Windows audio-import units have cumulative passing evidence across three frozen roots, not a single-root or single-Git-candidate 6/6. Every source hash/mtime remained unchanged; PASS sandboxes were removed, FAIL sandboxes were sealed/quarantined, and scoped residual-process checks were empty. |
| Public `integration` roots `imac-int-7f54506-r1`, `imac-int-7f54506-r2-retry5`, `imac-int-7f54506-r3-rifle`, `iwin-int-7f54506-r1`, and `iwin-int-7f54506-r2-retry3` | macOS: 7 passed / 5 failed, then 4 passed / 1 failed, then 1 passed fresh plus verify-only; Windows: 9 passed / 3 failed, then Weather passed / both Weapons failed | Exact frozen candidate `7f54506783a131695bafb97b89103488cb73d96c` used the public composed profile. macOS has cumulative passing evidence for all 12 unique units across three roots, not a single-root 12/12. Native Windows has cumulative passing evidence for 10 of 12 unique units and is not complete `integration` acceptance. Both remaining Weapons units repeatedly supplied malformed preview JSON; the authenticated Broker rejected those commands before runner/Wwise dispatch and no mutation occurred. Every source hash/mtime check passed, passing sandboxes were removed, failed sandboxes were quarantined, and no scoped residual process remained. |
| `run_codex_skill_campaign.py --profile integration_workflows_cross_version_6 ...` in frozen roots `a12`, `a20-int22-weather`, and `a24-int25-weather` | macOS: initial 4 passed / 2 failed; repaired Weather units 1 passed / 0 failed each | Six unique Wwise 2022.1/2025.1 workflow units have passing evidence across the three macOS roots (`runtime.platform=darwin`), using fresh memory-disabled Codex Terra tasks with medium reasoning and the default service tier. The initial failures and later diagnostic failures are sealed and quarantined; passing sandboxes were cleaned. Every lifecycle reports identical source-project full hash and mtime before and after. This is cumulative migration-before evidence, not one final-candidate 6/6 run and not fresh semantic validation of the later structured/advanced-query and closed-selector contract or the 2026-08-03 wording-normalized prompt digest. |
| `run_codex_skill_campaign.py --profile integration_workflows_cross_version_6 ...` in `campaign-integration-workflows-v1-terra-20260803-current-r1`, followed by single-unit repair roots `r2-int25-alarm-action-hop` and `r3-int22-alarm-action-hop` | macOS: full current-wording run 5 passed / 1 failed; repaired 2025.1 Alarm 1 passed / 0 failed; repaired-candidate 2022.1 Alarm guard 1 passed / 0 failed | Current natural-language prompts ran in fresh memory-disabled Terra tasks with medium reasoning and default service tier on macOS (`runtime.platform=darwin`). The sole failure was a redundant Action exact-ID read before any mutation. A narrow query-reference repair then passed both Alarm versions; both repair roots also passed `--resume --verify-only`. Weather and Harbor loaded the unchanged operate lane and passed on both versions in the full run. Across roots all six current prompt units have passing evidence, not one repaired-candidate 6/6 result. Seven passing sandboxes were cleaned, the failed sandbox remains quarantined, and all eight lifecycle records preserved source-project full hash and mtime. These named roots are macOS evidence; later old-component cross-host attempts are recorded next. |
| Legacy internal `integration_workflows_cross_version_6` roots `imac-wah-9e75a1a-r1`, `imac-wah-9b4de8f-r1`, and `iwin-wah-9b4de8f-r1` | macOS at `9e75a1a`: 6 passed / 0 failed plus verify-only; macOS at `9b4de8f`: 5 passed / 1 failed; Windows at `9b4de8f`: 3 passed / 3 failed | The first root belongs to commit `9e75a1aea496abcb9ef2a61e1da685adb99f4b01`; the latter two belong to `9b4de8f618855091a424700b50ab8b0fd1989270`. The two failed roots were frozen without verify-only replay. All three selected the old six-unit component profile, so none is current public `integration` evidence and they cannot be combined into a unified 12/12 result. |
| `run_codex_skill_campaign.py --profile integration_workflows_v2_cross_version_6 ...` across `r8`, `r12-2022`, `r23-2022-footsteps`, and `r24-2025-repairs` | macOS: initial Rifle 2 passed; repaired 2022.1 Weapons 1 passed; repaired 2022.1 Footsteps 1 passed; repaired 2025.1 Footsteps and Weapons 2 passed | All six unique fixed-baseline workflow units have passing evidence across fresh memory-disabled Codex Terra roots with medium reasoning and the default service tier on macOS (`runtime.platform=darwin`). This is cumulative evidence, not one final-candidate 6/6 run. Passing sandboxes were removed; failed or blocked diagnostic sandboxes remain sealed and quarantined; every recorded source full-tree hash and project mtime remained unchanged. The evidence applies only to the exact Rifle, Footsteps, and Weapons workflow paths and adds no per-API coverage credit. |
| Native-Windows `integration_workflows_v2_cross_version_6` roots `windows-v2-six-0dfea2b-r1`, `a516-w22-r1`, `a516-f25-r1`, `f1b-f25-r1`, and `f1b-w25-r1` | Windows: initial all-six root 3 passed / 3 failed; three later fresh repair passes, each with verify-only; one intermediate fresh repair failure | At `0dfea2b`, the full root passed 2022.1 Rifle/Footsteps and 2025.1 Rifle, failed the other three units, exited `1`, and had no verify-only replay. At `a516835`, 2022.1 Weapons passed fresh plus verify-only, while the 2025.1 Footsteps attempt failed and was frozen without verify-only. At `f1b6a51`, 2025.1 Footsteps and Weapons each passed fresh plus verify-only. The final Weapons root reconciled 12/12 Broker records, preserved exact quoted `@Volume`, left the source unchanged, and removed its passing sandbox. All six unique V2 units therefore have native-Windows passing evidence across frozen roots, not one root or candidate with a Windows 6/6 result. |
| `ci/test.sh --version all --mode matrix -- --collect-only -q` | Completed, 60 version-scoped invocations collected across focused live and destructive matrix nodes | This command checked strict real prerequisites through the runner, then collected 20 live and 40 destructive invocations without running test bodies. |
| Final #93 deterministic gates | macOS Program on route candidate `d45f75f5e75190d5b4e607a02aee2dcf38e73ab9`: 3655 passed / 2 skipped; native-Windows Program on runtime candidate `d05f1ecdc3b33fca83866e75669c65039877edd6`: 3642 passed / 15 skipped; both exit 0 | All ten five-version Switch assignment lanes accept only three business identities, compile exact relationship requests and opposite preconditions, remove normal `inline_typed` ingress, and retain Preview/authorization/execute-once/verifier safety. The route commit changes only the operate reference and its test. |
| `ci/test.sh --mode nonlive -- -q -ra` on exact runtime candidate `d05f1ecdc3b33fca83866e75669c65039877edd6` | 8632 passed, 110 skipped, 27 deselected; exit 0 | Final #93 broad runtime regression. No Codex, Wwise, live, or destructive body ran; declared skips receive no PASS credit. |
| `run_codex_skill_campaign.py --profile switch_assignment_business_1 --model gpt-5.6-terra --reasoning-effort medium --service-tier default --max-pre-action-retries 0` on exact route candidate `d45f75f5e75190d5b4e607a02aee2dcf38e73ab9` | macOS root `imac-sab-d45f75f-r2`: 1 passed / 0 failed plus identical verify-only; native-Windows root `iwin-sab-d45f75f-r2`: 1 passed / 0 failed plus identical verify-only | Both fresh memory-off Agents selected `switchContainer.addAssignment`, bound only the Switch Container, direct child, and Switch paths, and reached one Gateway-owned immutable Preview in eight accepted commands. No Wwise process or mutation was permitted. Earlier `d05f1ec` roots on both hosts remain frozen FAILs after invented aliases were rejected before dispatch. Temporary launchers were deleted and scoped residual-process checks were empty. |
| `ci/test.sh` / `ci\test.bat --version 2022.1|2025.1 --mode destructive -- -q -ra -k closed_gateway_workflows_across_selected_version` | macOS route candidate `d45f75f`: 2022.1 and 2025.1 each 1 passed / 12 deselected; native-Windows runtime candidate `d05f1ec`: 2022.1 and 2025.1 each 1 passed / 12 deselected; every invocation exit 0 | Real #93 add/remove assignment execution, opposite precondition, pair readback, cleanup, and broader closed-workflow regression. The later route-only commit does not change Gateway compilation, dispatch, verification, or cleanup. |
| Final deepened #93 deterministic and carry gates | Exact Program candidate `4c55ba6`: macOS 3659 passed / 2 skipped; native Windows 3646 passed / 15 skipped. MacOS Non-live candidate `d10dc23`: 8639 passed / 110 skipped / 27 deselected. Exact focused carry: `4389b6c` 410 passed; `4c55ba6` 452 passed / 4 skipped; `c874917` 76 passed. | Commits after `d10dc23` deepen only Gateway-owned business start/role continuations, compact audio-import receipts, and semantic evidence. Switch request materialization, native dispatch, relationship verifier, cleanup, and the previously recorded four real-Wwise rows remain unchanged. |
| `run_codex_skill_campaign.py --profile switch_assignment_business_1 ... --max-pre-action-retries 0` on final candidate `c874917220cb7723d60f86a14cea72c5d15cca52` | macOS root `imac-sab-c874917-r1`: 1 passed plus identical verify-only; native-Windows root `iwin-sab-c874917-r1`: 1 passed plus identical verify-only | Both fresh memory-off Terra Agents copied the Gateway-owned start and three ordered role continuations into one Preview. No Wwise process or mutation occurred. Windows used `InteractiveToken`/`Limited`; launch resources were deleted and both hosts reported zero scoped residual processes. Frozen Mac root `imac-sab-d10dc23-r1` contributes no credit. |
| Public `integration` Footsteps units on exact #93 candidate `3a31a05dd3636319cd228c648d462b5e1799fef6` | macOS roots `imac-int-footsteps-3a31a05-r20-int22` and `imac-int-footsteps-3a31a05-r21-int25`: one fresh PASS each plus identical verify-only; native-Windows roots `iwin-int-footsteps-3a31a05-r23-int22` and `iwin-int-footsteps-3a31a05-r22-int25`: one fresh PASS each plus identical verify-only | Cumulative 2/2 Footsteps acceptance per host, not one two-unit root. Each unit executed the Snow audio import plus Switch assignment and the Mud obsolete-assignment removal as two separately previewed project mutations with the independent business oracle. Every source full-tree hash and project mtime was unchanged, PASS sandboxes were removed, lifecycle errors were empty, temporary LaunchAgent or `InteractiveToken`/`Limited` Scheduled Task resources were deleted, and scoped residual processes were empty. Earlier repair roots remain frozen without credit; in particular Windows r20 completed the correct business effect but failed exact continuation-copy evidence. |
| Final #93 review-repair gates on exact candidate `83bbe6adf8822d1ebdc094ab4703809a324f49b0` | Focused campaign/Broker/harness: 778 passed / 13 skipped; Program: 3662 passed / 2 skipped; Non-live: 8685 passed / 110 skipped / 27 deselected; every invocation exit 0 | The review repair centralizes the public Draft command taxonomy and proves revision-chain rebinding for all 20 revision-producing subcommands, including audio media, object-list clearing, RTPC declaration, and type discovery. This commit and its documentation-only predecessor do not change the packaged Skill candidate `3a31a05`, public integration suite, or sealed Fresh roots. Program and Non-live started neither Codex nor Wwise; declared skips receive no PASS credit. |
| Targeted Harbor `integration` units on exact #79 candidate `4fb8dcca001ff474b1bddda659996fe21dd8f354` | Native Windows root `iwin-harbor-4fb8dcc-r5-full`: 2 passed / 0 failed plus identical verify-only; macOS: INT22 passed in `imac-harbor-4fb8dcc-r2` and INT25 passed in `imac-harbor-4fb8dcc-r3-int25`, with the all-PASS INT25 root passing identical verify-only | Both hosts have cumulative Fresh memory-off Terra PASS for the Wwise 2022.1 and 2025.1 Harbor business workflow. Windows additionally has one complete two-unit root. MacOS does not: later complete roots passed INT22 but were infrastructure-BLOCKED while CrossOver switched the shared `Wwise2019x64` bottle to 2025.1; those roots and every other BLOCKED root remain frozen without replay. No semantic FAIL occurred. Every recorded source full hash and project mtime was unchanged; PASS sandboxes were removed, BLOCKED sandboxes were sealed/quarantined, Windows temporary `InteractiveToken`/`Limited` tasks were removed, and scoped descendants were empty. The macOS diagnosis found 161 PID-1-reparented bottle helpers outside the old scoped residual check; after proved-idle cleanup, 2022.1 and 2025.1 smoke passed in 4.40 and 6.94 seconds, respectively, without receiving semantic credit. |
| Final #79 deterministic gates on exact evidence/docs candidate `66b9ee852d8a6436977fb7c09d44d194f748b48b` | Focused campaign/matrix/harness: 412 passed / 9 native-Windows skips; Program: 3682 passed / 2 platform skips; Non-live: 8712 passed, 110 skipped, 27 deselected; every invocation exit 0 | The focused gate covers explicit finite readiness sealing, child argv propagation, live lifecycle environment ownership, candidate-Skill runtime-cache exclusions, and the closed SoundBank bootstrap route. Program and Non-live started neither Codex nor Wwise. Commit `66b9ee8` changes only testing instructions and evidence inventory after packaged-Skill/harness candidate `4fb8dcc`, so it does not replace the recorded Fresh or real-Wwise candidate. |
| Four-operation #79 real-Wwise proof on exact transaction candidate `875f773aec5a9a7af450207b36d9e6a7359504b8` | macOS and native Windows: Wwise 2022.1 and 2025.1 each `1 passed / 12 deselected`; all four invocations exit 0 | One selected closed workflow executed `soundbank.setInclusions`, `soundbank.generate`, `soundbank.convertExternalSources`, and `soundbank.processDefinitionFiles` through Business Draft → immutable Preview → authorization → execute-once → operation-specific verification on every host/version pair. Source-project full hashes and mtimes remained unchanged, sandboxes were deleted, lifecycle cleanup completed, and scoped residual processes were empty. Later `a939181` grouped filter declarations, `7a15cbf` made business roles explicit, and `c17ee31` moved exact-name type ownership into the Gateway continuation. Those commits changed the public Adapter seam and therefore require the current-candidate 2025.1 revalidation recorded below; the version-specific native operation-registry materialization, dispatch, verifier, and cleanup lanes exercised here did not change, so this row remains the passing 2022.1 host/version evidence. |
| Post-review #79 Harbor Fresh proof on exact packaged-Skill candidate `c17ee31fe2fcb3cff7dc269fd5f340f2b85655b2` | macOS root `imac-harbor-c17ee31-r2-int25`: INT25 passed fresh plus identical `--resume --verify-only`; native-Windows root `iwin-harbor-c17ee31-r3-int25`: INT25 passed fresh plus identical verify-only | Both memory-off Terra tasks copied the Gateway-owned `soundbank.by_exact_name` continuation whose fixed prefix owns the `SoundBank` type and whose only caller-supplied suffix is the exact Bank name. The Windows Fresh and replay ran through temporary `InteractiveToken`/`Limited` Scheduled Tasks and ended with zero scoped descendants and no matching task. Earlier exact-candidate roots `imac-harbor-c17ee31-r1-int22`, `iwin-harbor-c17ee31-r1-int22`, and `iwin-harbor-c17ee31-r2-int25` were frozen as infrastructure-BLOCKED before any Agent turn when Wwise project loading exceeded their sealed readiness limits; source hashes/mtimes remained unchanged and they receive no semantic credit. The successful Windows root sealed a finite 600-second readiness allowance after the prior 2025.1 diagnostic took about 481 seconds before printing the server-started banner. Prior candidate `4fb8dcc` retains the cumulative INT22/INT25 evidence on both hosts; this row makes no current-candidate INT22 claim. |
| Current-seam #79 real-Wwise revalidation on exact candidate `c0d8778e64f25ace650a88c5f57a75ed762f1a38` | macOS and native Windows Wwise 2025.1 each `1 passed / 12 deselected`; both exit 0 | Both hosts exercised all four SoundBank operations through the final grouped-filter, role-bound public seam and the `pathlib`-owned external-source document boundary. The matching 2022.1 reruns receive no PASS credit: macOS timed out during Wwise project loading before the test body, while native Windows reached the exact `soundbank.generate` request but Wwise lost the transport after the bounded call timed out, leaving the transaction indeterminate. The failed sandboxes are not cited as evidence. Combined with the unchanged 2022.1 native lanes proven at `875f773`, the five-version deterministic compiler tests, and these dual-host final-seam 2025.1 passes, this is proportional cross-version/host evidence rather than a false claim that `c0d8778` itself passed all four host/version invocations. |
| Final #79 review-repair gates | Focused path/manifest regression on the final tree: 42 passed; Program on exact code candidate `333d1b689dc1e047c2e7830d251431044adc2b9d`: 3688 passed / 2 platform skips; Non-live on exact evidence tree `3a26b82a64a57342c627437a40bad5427032aec5`: 8718 passed / 110 skipped / 27 deselected; every invocation exit 0 | The final repair removes operation-specific SoundBank prose from the cross-operation control plane and replaces `os.path.relpath` with an explicit `PurePosixPath`/`PureWindowsPath` relative-path boundary. The fixed Program manifest includes POSIX, Windows-drive, and UNC cases covering case rules, parent traversal generation, mixed separators, spaces, Unicode, shell metacharacters, and cross-namespace rejection. Commits after `333d1b6` change only measured evidence documentation; packaged Skill and test code are identical. Program and Non-live started neither Codex nor Wwise. |
| #80 exact-artifact final deterministic gates | Exact packaged-Skill candidate `b00a73c101e2aaae2d3d59a60bfe3beafbaef4a2`: focused Adapter/Gateway/Broker/campaign/oracle regression 643 passed / 4 native-Windows skips; macOS Program 3720 passed / 2 platform skips; native-Windows Program 3707 passed / 15 POSIX-only skips; macOS Non-live 8751 passed, 110 skipped, 27 deselected; every invocation exit 0 | The final seam persists the live-sealed canonical Lua I/O root for file-free archive replay, rejects roleless Lua object binding, removes `bind-object` from Lua Draft projections while retaining tab import's required location binding, discloses recursive strict-JSON values including null plus bounded operation-specific argument-key exclusions, and rejects CLI Lua on Authoring before project reads, Preview, or dispatch. POSIX, Windows-drive, UNC, traversal, case, mixed-separator, space, Unicode, and shell-metacharacter archive paths are covered without foreign-host parsing. Program and Non-live started neither Codex nor Wwise; declared platform skips receive no PASS credit. |
| #80 proportional real-Wwise exact-artifact proof | Historical native-request candidate `b0e539a3e8452a38314f72db903ccc48ad0f997c`: macOS and native Windows Wwise 2025.1 each passed inline Lua, Core Lua file, and tabular import; CLI Lua ended the transport once on each host and remains a non-retry explicit boundary. Exact final packaged-Skill candidate `b00a73c` then passed the three targeted native-Windows Wwise 2025.1 workflows again (`3 passed / 12 deselected`, exit 0) and executed TYP23/TYP25 Core Lua inside the Fresh root below. | The final review repairs change the public contract, continuation, host gate, Draft actions, and archived evidence, not inline/Core/tab native request serialization. Historical macOS execution remains proportional native-dispatch evidence; final-candidate Windows destructive and Fresh runs prove the current seam without claiming a final-candidate macOS rerun. Across credited evidence exact source artifacts and source projects remained unchanged, passing sandboxes were removed, and scoped residual processes were empty. |
| #80 final Fresh Agent proof and blocked macOS diagnostics | Exact candidate `b00a73c`: native-Windows root `iwin-exact-review-b00a73c-r3-lua2` passed TYP23 and TYP25 Core Lua 2/2 in one fresh Terra/medium/default attempt and passed identical `--resume --verify-only`; the temporary task attested `InteractiveToken` / `Limited`, returned 0, was deleted, and ended with zero root-scoped processes. The earlier tab PASS roots belong to `b113e83`; they remain only proportional historical evidence because the later review repairs leave tab's required binding and continuation unchanged, not same-candidate PASS. | The Windows Agent copied the final no-binding Lua continuation and completed both immutable Preview/execute/weak-verifier workflows against real Wwise. Mac root `imac-exact-review-b00a73c-r1-lua2` was frozen BLOCKED after an overlapping real pytest contended for the shared CrossOver bottle; r2 was frozen as 0 Agent turns / 0 dispatch after 2023.1 WAAPI readiness timed out at the sealed 600-second limit, leaving TYP25 pending. Neither Mac root is replayed or credited. Source full hashes/mtimes remained unchanged and failed sandboxes were sealed/quarantined. Windows pre-root launcher diagnostics r1/r2 found a missing ignored live fixture, created no campaign root, and receive no semantic status. |
| #81 final Authoring UI business-declaration deterministic and real-host gates | Exact candidate `cba7507d26d22a7569f966838676bcb6b84982a5`: focused public Adapter/Gateway/UI-plan regression 171 passed; Program 3751 passed / 2 platform skips; Non-live 8791 passed, 111 skipped, 27 deselected; every credited invocation exit 0. Native-Windows Wwise Authoring 2022.1 on runtime predecessor `e1480b1` passed the public capture/SaveProject/register/unregister workflow 1/1; later production changes affect only Gateway-owned command-inventory responsibility and Agent-facing operation selection, not dispatch, preconditions, verification, or cleanup. | All 20 version/operation lanes use `authoring-ui-business/v1`; old UI inline typed and Composer inputs are absent. The Windows real workflow ended `isDirty=false`, preserved the source full hash `d78b393a8db1af77f10d03003316fa4a804d234345fecd15e3e2f67e6ce2e1e2` and mtime, stopped Wwise, removed launch tasks, and left no scoped process. macOS Authoring 2022.1 and 2025.1 never became WAAPI-ready and remain BLOCKED with no behavior credit; their source projects were unchanged and scoped processes were cleaned. Mac root `imac-aui-f157f15-r8` passed capture plus SaveProject 2/2 and identical replay; exact-candidate root `imac-aui-cba7507-r9-save` passed SaveProject plus replay. Windows predecessor root `iwin-aui-f157f15-r1` passed capture and froze a semantic SaveProject FAIL; exact-candidate root `iwin-aui-cba7507-r2-save` passed SaveProject plus replay through an attested `InteractiveToken` / `Limited` task. This is cumulative proportional route evidence, not a claim that either current candidate had one 2/2 root. Program and Non-live started neither Codex nor Wwise. |
| #82 final Debug business-intent and terminal-journal gates | Exact candidate `3a9a137a54ced6a7a8749d4ad573d4b638b2706d`: focused Debug/dispatcher/transaction/docs regression 483 passed; Program 3751 passed / 2 platform skips; Non-live 8857 passed, 111 skipped, 27 deselected; both review axes PASS and every credited invocation exit 0. | All 23 exact Debug version/operation lanes use `debug-business/v1`. The Agent supplies only enabled/disabled for asserts or automation mode, or one zero-value deliberate restart/assert/crash intent; no acknowledgement, native args/options, disconnect classification, or retry plan is public. Gateway owns the fixed internal marker, explicit-confirmation-only dangerous path, and one terminal journal: accepted returns are effect-unverified, normalized expected-disconnect exceptions are `INDETERMINATE`, and explicit non-OK results are `EXECUTION_FAILED`. Every terminal path is execute-once with no reconnect, retry, generic verify, or next command. Old Debug inline-typed production code is absent and generic native routes remain blocked. Per #82, Program and Non-live are primary proportional evidence; no real Wwise crash, assert, or server restart and no Fresh Agent campaign was run or claimed. |
| #83 final compound Undo deterministic gates | Exact candidate `bcf51233a08ccd8a334349b64bfffa7f3edfd307`: focused compound Adapter/Gateway/Broker/campaign/harness regression 1009 passed / 13 native-Windows skips; Program 3780 passed / 2 platform skips; Non-live 8906 passed / 111 skipped / 27 deselected; both review axes PASS and every credited invocation exit 0. | All five `waapi.undoGroup` lanes use `compound-undo-business/v1`. One display name plus an ordered list of checked, non-overlapping Business Draft capabilities compiles child snapshots, exact begin/child/end dependencies, cancel-on-failure, aggregate verification, and one immutable Preview. Public child schemas, call handles, revision arithmetic, native request fragments, dependency edges, Composer ordering grammar, and fallback are absent. Program and Non-live started neither Codex nor Wwise; declared skips receive no PASS credit. |
| #83 proportional real-Wwise compound execution | Exact production-Skill candidate `39dc245`: macOS and native Windows Wwise 2022.1 and 2025.1 each passed `test_compound_undo_business_draft_executes_and_cancels_without_retry` (`1 passed / 15 deselected`, four invocations, every exit 0). | Each host/version pair exercised one successful grouped change plus the actual child-failure cancellation and non-retry shape through the public Business Draft, immutable Preview, authorization, execute-once, and aggregate verifier. Source SampleProjects remained unchanged, sandboxes were removed, lifecycle cleanup completed, and scoped residual processes were empty. Commits through `bcf5123` after `39dc245` change only the Fresh Broker/campaign harness, its tests, and testing documentation, not the packaged Skill tree or real transaction path. |
| #83 final cross-platform Fresh Agent proof | Exact candidate `bcf51233a08ccd8a334349b64bfffa7f3edfd307`: macOS root `imac-cub-bcf5123-r7` and native-Windows root `iwin-cub-bcf5123-r7` each passed `compound_undo_business_1` 1/1 fresh with `gpt-5.6-terra`, medium reasoning, default service tier, then passed an identical `--resume --verify-only` audit. | Each fresh memory-off Agent completed the reviewed parent plus two interleaved child Draft protocol, checked both children without child Previews, and produced one compound Preview in 16 accepted commands. All Broker, exact-protocol, no-direct-WAAPI, no-execute, no-inline-code, no-unexpected-command, Skill-integrity, workspace-integrity, and final-report gates passed; Wwise was not started. macOS used one-shot LaunchAgents; Windows used temporary `InteractiveToken` / `Limited` Scheduled Tasks. All launch resources were removed and both hosts ended with zero scoped residual processes. Roots r1-r6 remain frozen without replay or PASS credit; their launcher, Broker-topology, Draft-ownership, candidate-runtime, and genuine Agent-path incidents are recorded in `tests/semantic/HARNESS_PITFALLS.md`. |
| #84 final generic Core business-declaration deterministic gates | Exact final candidate `2354bd7fdaa10ee51d1260cc62b30dba88aaa237`: macOS Program 3970 passed / 2 platform skips and native-Windows Program 3957 passed / 15 POSIX-only skips. Runtime predecessor `912066b7397e7b01d6c1fcb3e01a3d9c9be2bcaf`: final focused Core/schema/Broker regression 164 passed plus generated-inventory/release-report checks 16 passed and macOS Non-live 9162 passed / 111 skipped / 27 deselected; every credited invocation exit 0. | All 55 exact `generic-core-project-object` version/API rows are sealed by row count and digest `caf467378cbabccb637cd93d18cc4e87e5356d409ce110da1f040825af4245ed`. Public `core-business/v1` declarations retain user business scalars and exact artifacts while Gateway owns GUID placement, metadata handles, native enums/arrays, request shape, revision, Preview, and continuation; legacy `typed-call` and `draft-apply` construction are blocked. The final review repair accepts empty points only for non-Custom attenuation sources and discloses that omitted project-save checkout preserves Wwise's native `true` default, so an explicit user prohibition must remain `auto_check_out=false`. Program and Non-live started neither Codex nor Wwise. |
| #84 proportional real-Wwise Core proof | Exact runtime candidate `3b93202bc968b09aa0cfa0659849427359c0e435`: macOS and native Windows Wwise 2022.1 and 2025.1 each passed `test_core_business_public_read_and_result_schema_mutation` (`1 passed / 16 deselected`, four invocations, every exit 0). | Each host/version pair used public `object.diff`, live Volume metadata discovery, and a Core `pasteProperties` Business Draft through immutable Preview, authorization, execute-once, result-schema verification, and exact `volume-db=-7.25` readback. Source project hashes/mtimes remained unchanged, sandboxes were deleted, cleanup completed, and scoped residual processes were empty. Later routing/catalog/Fresh changes do not alter this diff/paste dispatch or verifier shape. The later non-Custom attenuation repair is deterministic-only evidence and is not claimed as a real-host execution here; this row is proportional representative proof, not all-55 live coverage. |
| #84 final cross-platform Fresh Agent proof | Exact candidate `2354bd7fdaa10ee51d1260cc62b30dba88aaa237`: macOS root `imac-core-2354bd7-r15` and native-Windows root `iwin-core-2354bd7-r15` each passed `core_business_1` 1/1 fresh with `gpt-5.6-terra`, medium reasoning, default service tier, then passed an identical `--resume --verify-only` audit. | Both fresh memory-off Agents used six accepted Gateway commands (`operations`, exact `request-schema`, `draft-start`, explicit `auto_check_out=false`, `draft-check`, and one Preview), produced one closed `project.save` transaction, and stopped without execute, Wwise, mutation, or workspace/Skill changes. All Broker, exact-protocol, closed-Core-request, no-direct-WAAPI, no-inline-code, no-unexpected-command, integrity, and final-report gates passed. macOS used one-shot LaunchAgents; Windows proved desktop session 1 and used temporary `InteractiveToken` / `Limited` Scheduled Tasks. All launch resources were removed and both hosts ended with zero scoped residual processes/tasks. Windows `iwin-core-33f668f-r13` remains a frozen semantic FAIL without replay: the Agent omitted explicit false, the Broker rejected before Gateway/Wwise dispatch, and no mutation occurred. Pre-root SSH quoting, Task XML attestation, Store-Python, and empty-worktree-Poetry diagnostics receive no semantic or Program credit and are recorded in `tests/semantic/HARNESS_PITFALLS.md`. |
| #85 final media/build business-read deterministic gates | Exact packaged-Skill/Program candidate `9e09a99e26c69949789b8ee2f921c245d4da02c0`: focused #85/execution/inventory/capability regression 140 passed; macOS Program 4048 passed / 2 platform skips; native-Windows Program 4033 passed / 17 platform-specific skips. Exact Non-live evidence candidate `0b2a78a` changes only the measured README-count assertion and passed 9235 / 111 skipped / 27 deselected on macOS. Every credited invocation exited 0. | All 16 exact `generic-core-media-build` version/API rows are sealed by row count and digest `eb0692ad57f0a504bf110f38355997bb9abca7519ed412c4ed97c223a6a0decf`. `media-build-business/v1` exposes only exact AudioFileSource or SoundBank identity, finite region/count values, bounded Media Pool meanings/filters, and exact local audio artifacts; Gateway owns versioned native fields, exact-case field discovery, host-path localization, peak decoding, inclusion enrichment, sorting, completeness, result ceilings, and `core-call`. All 16 execution contracts are direct bounded reads; typed-call, typed containers, typed Drafts, transaction authorization, and native fragments are absent. The initial SSH `pwsh -File -` stdin diagnostic produced no test-context header and receives zero test credit; the copied-file rerun is the recorded Windows gate. |
| #85 proportional dual-host real-Wwise proof | macOS exact candidate `2bd2364`: Wwise 2022.1 and 2025.1 each passed `test_media_build_business_reads_across_selected_version` (`1 passed / 17 deselected`). Native Windows exact product candidate `67c7c0a`: the same two version invocations each passed `1 / 17 deselected`; later `2bd2364` changes one capability-catalog expectation only and leaves the packaged Skill and real test body identical. | Each host/version exercised region peaks, trimmed peaks, and enriched SoundBank inclusions; Wwise 2025.1 additionally exercised bounded Media Pool discovery/filter/projection. Every source SampleProject hash/mtime remained unchanged, passing sandboxes were removed, cleanup completed, and no Wwise process remained. No Fresh Agent campaign was run: #85 requires it only for declaration-induced routing ambiguity, while all four exact API intents expose distinct version-scoped `request-schema -> core-call` continuations and deterministic non-bypass coverage. No semantic PASS is claimed beyond these real representative read shapes. |
| #86 final remaining-Core deterministic gates | Exact packaged-Skill candidate `98d9e70b6b3ec965bfb00eb6aad945cd0b70999b`: macOS Program 4126 passed / 2 platform skips. Exact final harness/evidence candidate `a0a01785b20c98c50464380c000d11c2e05e8a45`: native-Windows Program 4111 passed / 17 platform skips and macOS Non-live 9324 passed / 111 skipped / 27 deselected; focused final Business/267 accounting regression 50 passed. Every credited invocation exited 0. | All 43 exact `generic-core-remaining` rows are sealed by digest `a7541ae6dad3c8c033b13089c13c1faad9a2688aee985c72e5c414fdb812fa8a`: 30 executable Game Parameter, Sound active-source, and source-control lanes use `project-setting-business/v1` or `source-control-business/v1`; three provider lanes retain the human credential boundary; ten Undo end/cancel lanes remain compound-only. Game Parameter names resolve inside the Draft through a Gateway-fixed `GameParameter` type, and dedicated `--minimum`, `--maximum`, and curve-outcome flags replace the internal generic field envelope. Gateway owns GUIDs, relationship/type checks, native enums and paths, projections, Preview, authorization, and verification. Program and Non-live started neither Codex nor Wwise. |
| #86 proportional dual-host real-Wwise proof | Exact packaged-Skill candidate `590a416a8ca7c29eca293d23de544118a1a2c758`: macOS and native Windows Wwise 2025.1 each passed `test_remaining_core_business_project_setting_and_external_read` (`1 passed / 18 deselected`, both exit 0). | Each host executed one temporary Game Parameter range change with operation-specific `@Min`/`@Max` readback and one bounded external `sourceControl.getSourceFiles` result-schema/projection lane. Source project hash/mtime remained unchanged, passing sandboxes were removed, cleanup completed, and scoped residual processes were zero. Later packaged changes deepen only the Agent-facing exact-name and dedicated declaration continuation; native request construction, execution, and verifier shapes are unchanged and covered by the final deterministic/Fresh evidence. |
| #86 final cross-platform Fresh Agent proof | The packaged Skill tree is identical from `98d9e70` through final harness candidate `a0a0178`. macOS root `imac-pset-98d9e70-r4` passed `project_setting_business_1` 1/1 fresh and identical verify-only; root `imac-pset-81aeb6e-r5` independently passed 1/1 fresh after the Windows-only reconciliation repair. Native-Windows final root `iwin-pset-a0a0178-r6` passed 1/1 fresh and identical verify-only with `gpt-5.6-terra`, medium reasoning, and default service tier. | Each credited Agent selected the project-setting route from natural language, bound `WeatherIntensity` through the copy-ready typed-name branch, supplied only the dedicated high-level range outcome, and produced one immutable `waapi.call` Preview without execute or Wwise. Broker, exact protocol, closed request, no-direct-WAAPI, no-inline-code, no-unexpected-command, Skill/workspace integrity, and final-report gates passed. Windows used temporary active-desktop `InteractiveToken` / `Limited` tasks; macOS used one-shot LaunchAgents. Launch resources were removed and residual process/task counts were zero. Roots r1-r3 and Windows r4-r5 remain frozen without replay or PASS credit; their Draft-taxonomy, identity-query contradiction, fixture-WAQL, public-parameter, and 267-accounting incidents are recorded in `tests/semantic/HARNESS_PITFALLS.md`. |
| Final #96 Program gates on exact Git candidate `1fc30be7f88015e1b1c415eadfe0e9afd710756f` | macOS `3811 passed / 2 skipped`; native Windows `3798 passed / 15 skipped`; both exit 0 | All 47 exact issue rows are cleared from ticket ownership: 44 fixed query/metadata/profiler/Debug rows are `generic-fixed-query-metadata / already_deep`, and three selection rows are `generic-fixed-command-audited-deep / already_deep`; every row has no leaked mechanic and no owner issue. The final candidate seals the two-layer business/advanced query cutover, all-Sound business alias, and separate primary/audited query dispatch counts. Windows ran directly through SSH with the worktree-local Poetry environment; neither Program gate started Codex, Wwise, or a network client. |
| `ci/test.sh --mode nonlive -- -q -ra` on exact evidence commit `595840335a38d2a35d35ffcec64ba651ae13e605` | 8990 passed, 111 skipped, 27 deselected; exit 0 | Final #96 broad regression, including two-layer public documentation, omission-aware replay of the sealed optional query-repair protocol, separate primary/audited dispatch validation, and positive/negative archive checks. This commit changes only the evidence inventory relative to packaged candidate `1fc30be`; no live/destructive body, Codex task, or Wwise process ran, and declared skips receive no PASS credit. |
| #87 final runtime-inspection Business seam deterministic gates | Exact zero-ID repair candidate `114e9486cb247bf7eed6b0cf6544fcd395049e03`: macOS Program 4223 passed / 2 skipped, native-Windows Program 4208 passed / 17 skipped, focused runtime/transaction/public-route regression 1392 passed, and macOS Non-live 9430 passed, 111 skipped, 27 deselected; every credited invocation exited 0. Exact predecessor `1cc590cf7d66e0d5b84d1e27cc4ddd9f9841c02e` independently passed macOS Program 4226 / 2 skipped, native-Windows Program 4211 / 17 skipped, and macOS Non-live 9433 / 111 skipped / 27 deselected before three invalid-zero parameter cases were correctly removed. | All 94 runtime-inspection/control version rows are sealed as completed family `generic-core-runtime-inspection` with digest `b66b1f4d66d8d77b456b98041c7e14fa2d383e02bae02b4a17fabfb85261d593`; #87 is absent from the remaining ticket families. Review repair replaced reversible native IDs with random project/build/endpoint-bound `trh1` capabilities, exact live-row fingerprints, execution-time drift checks, verified-destroy retirement, bounded retired-record pruning, same-native-ID Gateway generation invalidation, and a project-external state-store guard. Real Wwise 2022.1 Authoring proved that native transport ID `0` is live, so the final seam accepts the complete uint32 domain across verification, cleanup, handle storage, materialization, and execution revalidation while still rejecting booleans, negatives, overflow, strings, and missing IDs. Wwise exposes no transport-generation field beyond `transport`, `object`, and `gameObject`, so an exact identical external replacement remains a truthful native-unobservable boundary. Program and Non-live started neither Codex nor Wwise. |
| #87 proportional dual-host real-Wwise Console proof | Packaged runtime candidate `138f06622ef5c12ce264851670d3084a5762d67b`: macOS and native Windows Wwise 2022.1 and 2025.1 each passed `test_runtime_business_profiler_and_authoring_boundaries` (`1 passed / 19 deselected`, four invocations, every exit 0). | Each host/version exercised the Profiler read/control path and proved that Remote/Transport return `AUTHORING_HOST_REQUIRED` before project read or native dispatch on WwiseConsole. Source project hashes/mtimes remained unchanged, sandboxes were removed, and scoped processes were empty. This is truthful Console boundary evidence; the separate matching-Authoring lifecycles are recorded in the next row. Later packaged changes preserve the same native Profiler and host-boundary paths while deepening transport capability binding. |
| #87 matching-Authoring Profiler, transport, and Remote lifecycles | Exact packaged candidate `114e9486cb247bf7eed6b0cf6544fcd395049e03` macOS Wwise Authoring 2022.1 root `waapi-authoring-runtime-114e948-r4` passed `test_runtime_business_profiler_and_transport_lifecycle_on_authoring` (`1 passed / 1 deselected`, exit 0). Test-only successor `5de155691d0a0312728517ec19a33421a4e8ec74` retained the identical packaged Skill and root `waapi-authoring-remote-5de1556-r7` passed `test_runtime_business_remote_connection_lifecycle_on_authoring` (`1 passed / 2 deselected`, exit 0). | The first lifecycle enabled then disabled Voices capture, created live transport ID `0`, exposed only opaque `trh1`, read state, stopped, destroyed, and independently ended with an empty transport list. The second discovered the official installed GameSimulator through `remote.getAvailableConsoles`, supplied its exact `127.0.0.1` / `Replay Instance` / `24025` selector through the high-level Remote Draft, verified connected, then copied the zero-input audited `remote.disconnect` continuation and verified disconnected. Both used isolated optional-plugin-free copies; final `isDirty=false`, source full hash `0094292bd34fd6581cff062ce8aa6f715aba82556d7f783847e478c89913836e` and mtime `1787737795.9923954` were unchanged, and Wwise/GameSimulator residual processes were zero. |
| #87 final cross-platform runtime-control Fresh Agent evidence | The packaged Skill tree is identical from exact candidate `114e9486cb247bf7eed6b0cf6544fcd395049e03` through test-only successor `5de1556`. macOS root `imac-runtime-1cc590c-r1` had already passed `runtime_control_business_1` 1/1 fresh plus identical verify-only on the final pre-zero-ID packaged seam. Native-Windows root `iwin-runtime-114e948-r4` passed `RUNTIME25-PROFILER-VOICES-PREVIEW` 1/1 fresh and then passed identical verify-only with the sealed standalone Codex path. Earlier exact `f8968f7` Windows roots r2/r3 remain frozen `BLOCKED` with 0 PASS. | Both credited memory-off Terra Agents selected the reviewed Gateway route and produced the Voices-enable immutable Preview without execute or Wwise. Windows r4 used one active-desktop `InteractiveToken` / `Limited` Scheduled Task, sealed an attempt manifest, exited zero, and left zero matching processes or tasks; its verify-only replay started neither Codex nor Wwise. The earlier Windows roots stalled before the first completed Skill read while unrelated long Codex work shared the desktop; they received no semantic credit and were not replayed. |
| `test_gateway_read_only_matrix_runs_once_against_copied_sandbox` on macOS and native Windows, Wwise 2022.1 and 2025.1, at packaged runtime candidate `e012fcc` | Four host/version invocations, each 1 passed / 3 deselected; every invocation exit 0 | One composite read-only Gateway matrix per host/version exercised business object queries, live type/property discovery, Console selection boundary, profiler capture, and the applicable Debug validation boundary. Wwise 2025 Release returned the explicit `DEBUG_BUILD_REQUIRED` boundary rather than Debug execution credit. Every source hash/mtime remained unchanged, each sandbox was deleted, and cleanup left no residual scoped process. Later packaged changes only clarified and bound the same closed query business schema/protocol and were re-proved by the final Fresh query row. |
| `run_codex_skill_campaign.py --profile typed_input_cross_version_25 --case-id TYP22-GENERIC-OBJECT-QUERY --model gpt-5.6-terra --reasoning-effort medium --service-tier default` on exact Git candidate `1fc30be7f88015e1b1c415eadfe0e9afd710756f` | macOS root `imac-query-1fc30be-r15-repair`: 1 passed / 0 failed plus identical verify-only; native-Windows root `iwin-query-1fc30be-r16-repair`: 1 passed / 0 failed plus identical verify-only | Both fresh memory-off Agents completed the same-PASS-root repair: broad `Music` returned structured live type candidates, each Agent selected the first exact `MusicSegment`, confirmed one object, and then issued the full bounded `CombatMix` business query. Gateway owned native WAQL construction; each host returned the exact eight Sound rows, grouped 5/3 across the two Output Buses without reaching the 12-row bound. Source full hashes and project mtimes were identical before/after, PASS sandboxes were removed, lifecycle errors were empty, and both verify-only checks started neither Codex nor Wwise. Windows Fresh and replay used temporary active-desktop `InteractiveToken`/`Limited` tasks; all Windows tasks and macOS LaunchAgents were removed. Earlier r7-r15 non-PASS roots remain frozen without replay; they record prompt lint, object-catalog or late-schema deviations, the closed `sound`/`all-sounds` vocabulary seam, and archive-only BLOCKED layers, and contribute no final PASS credit. |
| #88 pre-review SoundEngine deterministic gates | Exact packaged-Skill candidate `8945ba78fa7d12ef105511986e51a0313a1da23f`; macOS Program on test-only successor `8532892` passed 4266 / 2 platform skips and native-Windows Program passed 4251 / 17 platform skips. Focused transaction-continuation regression passed 211. Exact harness candidate `80c77a9ef39c637dcc1b4a1a1dd45cb810e710fe` passed Non-live 9480 / 111 skipped / 27 deselected after the independent Draft-revision set was extended; every credited invocation exited 0. | All 124 `generic-soundengine-runtime` rows are sealed by digest `5075fdcc32810059d6a3fee10499ff6823eea0be4c300dfb717bede6697c6ced`. The 26-operation `soundengine-control-business/v1` surface accepts bound Wwise roles, opaque runtime capabilities, stable actions/modes/layouts, and bounded business values while Gateway owns native IDs, sentinels, enums, overloads, arrays, channel configuration, gain conversion, lifecycle retirement, drift checks, Preview, and result projection. The production repair also preserves an explicit external transaction state root in every copy-exact continuation on POSIX and Windows. Program and Non-live started neither Codex nor Wwise; declared skips receive no PASS credit. This row predates the final review repair and is retained as proportional evidence, not final-candidate closure. |
| #88 pre-review proportional dual-host real-Wwise proof | The packaged Skill is identical from `8945ba7` through evidence candidate `80c77a9`. On macOS and native Windows, Wwise 2022.1 and 2025.1 each passed the Console boundary test (`1 passed / 19 deselected`) and matching Authoring SoundEngine workflow (`1 passed / 3 deselected`): eight host/version invocations, every exit 0. | Console runs proved the reviewed host boundary. Authoring runs dispatched the monitor-log call and result-schema checked it, registered two opaque game objects, exercised position/multiple-position, default and explicit listeners, obstruction/occlusion, scaling, output-bus volume, listener spatialization, stop-all, and unregister cleanup. macOS used the Wine wrapper's `start.exe /wait` with the exact converted sandbox `.wproj`; Windows used active-desktop `InteractiveToken` / `Limited` tasks. Only the exact known cache or Project Load Log warning was acknowledged, `getProjectInfo.path` matched the private sandbox, every source hash/mtime remained unchanged, temporary tasks were removed, and Wwise/8080/8090 residual counts ended at zero. The later review repair only completes public list-limit disclosure and Fresh coverage; it does not change native materialization or execution, so this remains proportional real-host evidence rather than a final-candidate rerun claim. |
| #88 predecessor monitor Fresh Agent proof | Exact candidate `2363c44a650c2d5133e832a8241c4e16c34f565b`: macOS root `imac-soundengine-2363c44-r1` and native-Windows root `iwin-soundengine-2363c44-r1` each passed `soundengine_business_1` 1/1 fresh with `gpt-5.6-terra`, medium reasoning, default service tier, then passed an identical `--resume --verify-only` audit. | Both memory-off Agents converted the natural exact monitor-message intent into `draft-start`, the closed SoundEngine declaration, `draft-check`, and one immutable `ak.soundengine.postMsgMonitor` Preview without execute or mutation. The sealed profile is `offline_only=true`, `live_config.used=false`, and `wwise_started=false`. Windows Fresh and replay used temporary active-desktop `InteractiveToken` / `Limited` tasks; both hosts retained one sealed attempt manifest, removed launch resources, ended with zero scoped descendants/tasks, and kept Wwise plus WAAPI-listener counts at zero. The operator-side accidental Wwise Launcher start before replay was outside the campaign, cleaned before either audit, and is recorded in `tests/semantic/HARNESS_PITFALLS.md` without semantic credit. This is one historical monitor unit, not the final four-unit event/game-object/listener closure evidence. |
| #88 final review-repair deterministic gates | Final packaged-Skill candidate `425793ec147e0abeb34a2c9139d465f14326ce40` passed macOS Program 4269 / 2 skipped, native-Windows Program 4254 / 17 skipped, macOS Non-live 9488 / 111 skipped / 27 deselected, and the SoundEngine/catalog-focused set 47 passed / 27 environment skips; every credited invocation exited 0. Test-only semantic-grader successor `73accee0ec7f4c0a19155a7a82752f1b10a82730` retains the identical packaged Skill and passed the final 47-test focused set. | Review repairs replay dynamic Gateway-owned IDs from durable Business Drafts, expose fixed-type exact-name continuations for SoundEngine roles, distinguish runtime Game Object registration from Authoring `object.create`, distinguish runtime Profiler Capture Log from Authoring Log, and grade final prose by Preview status rather than exact translated nouns. All 124 exact rows and the sealed digest remain unchanged; Program and Non-live started neither Codex nor Wwise. |
| #88 final targeted Fresh Agent evidence | On packaged candidate `d922117`, macOS root `imac-soundengine4-d922117-r4` passed all four Monitor/Game Object/Event/Listener units in one fresh root. Candidate `425793e` root `imac-soundengine4-425793e-r5` then completed all four closed Previews with every Broker, exact-protocol, closed-request, no-execute, no-unexpected-command, and integrity gate passing; its sealed summary nevertheless remains 2 PASS / 2 FAIL because the retired grader required the exact nouns `监控` and `游戏对象`, while the normal replies used `Profiler Capture Log` and `运行时对象`. Manual review identified those two outcomes as grader false negatives, but the frozen root receives no formal semantic PASS credit and is superseded by the later formal 4/4 roots below. On native Windows, `iwin-soundengine4-d922117-r4` passed Game Object, Event, and Listener; exact final Skill plus test-only grader candidate `73accee` root `iwin-soundengine4-73accee-r6-monitor` passed the repaired Monitor unit 1/1 fresh and an identical `--resume --verify-only` audit. | All credited tasks used fresh memory-off `gpt-5.6-terra`, medium reasoning, default service tier, offline-only production Gateway, and no mutation. Windows used active-desktop `InteractiveToken` / `Limited` Scheduled Tasks; the final Monitor Fresh and replay each exited 0 with one sealed manifest, zero campaign descendants, and no remaining task. During replay the user's independent ReWwire WwiseConsole remained PID 12464 on port 18090 before and after, while the campaign stayed `offline_only=true`, `live_config.used=false`, and `wwise_started=false`; 8080/8090 remained unused. This proves the unrelated Console was not a conflict and corrects the earlier operator-side machine-wide zero-process preflight. Earlier FAIL/BLOCKED roots remain frozen without replay. This is cumulative targeted acceptance, not a claim that every host has one final-candidate 4/4 runner summary. |
| #88 final closure deterministic gates | Exact final candidate `aefa9cea6af2b843d0be072c6bac958a9ab8ca9f`: focused final storage/result-shape regression passed 39; macOS Program passed 4286 / 2 platform skips, native-Windows Program passed 4268 / 20 platform skips, and macOS Non-live passed 9514 / 111 skipped / 27 deselected; every credited invocation exited 0. | The final review repair bounds the runtime Game Object handle store, rejects state/root/records links plus Windows junction/reparse points through the shared filesystem-security detector, makes Skill-locator isolation lexical across POSIX/drive/UNC spellings, and normalizes real `getState` / `getSwitch` wire results from `{return:{id,name}}` into one stable bounded business object with fail-closed malformed-result coverage. All 124 exact `generic-soundengine-runtime` rows remain sealed by digest `5075fdcc32810059d6a3fee10499ff6823eea0be4c300dfb717bede6697c6ced`; no typed/native fallback was restored. Program and Non-live started neither Codex nor Wwise. The Windows POSIX symlink tests are three explicit platform skips; the three off-host mocked reparse cases passed natively on Windows. Earlier Store-Python and empty-Poetry preflights stopped before collection and receive no test count. |
| #88 final expanded dual-host real-Authoring proof | On packaged candidate `ea36a60`, macOS Wwise Authoring 2022.1 and 2025.1 each passed `test_soundengine_business_runtime_and_spatial_families_on_authoring` 1/1. On documentation-only successor `1caca30`, native Windows Wwise Authoring 2022.1 and 2025.1 each passed the same test 1/1 through active-desktop `InteractiveToken` / `Limited` tasks. | Every host/version invocation exercised monitor logging, opaque Game Object registration, `postEvent -> seekOnEvent -> stopPlayingID`, `setState -> getState`, `setSwitch -> getSwitch`, position/multiple-position, listener, obstruction/occlusion, scaling, output-bus gain, spatialization, stop-all, and bounded unregister cleanup. The first macOS 2022.1 diagnostic exposed the real result wrapper and failed only the obsolete flat test expectation; after the Gateway projection repair, all four final invocations passed. macOS launched the exact Wwise executable plus bottle-converted sandbox path; both versions used the exact-title/exact-button `Project Load Log` helper. Windows used the matching executable and sandbox path inside temporary tasks. Every source full hash and mtime remained unchanged, PASS sandboxes were deleted, launch resources were removed, and Wwise plus 8080/8090 residual counts ended at zero. Later candidates through `aefa9ce` add only fail-closed local handle-storage security and deterministic tests; native request construction, dispatch, result projection, and normal real-directory lifecycle are unchanged, so this remains proportional real-host evidence rather than a same-candidate rerun claim. |
| #88 final same-candidate cross-platform 4/4 Fresh Agent proof | Exact final candidate `aefa9cea6af2b843d0be072c6bac958a9ab8ca9f`: macOS root `imac-soundengine4-aefa9ce-r9` and native-Windows root `iwin-soundengine4-aefa9ce-r10` each passed all four Monitor/Game Object/Event/Listener units in one fresh root with `gpt-5.6-terra`, medium reasoning, default service tier, then passed identical `--resume --verify-only` audits. | Both roots sealed 4 PASS / 0 FAIL / 0 BLOCKED, one attempt manifest, offline-only production Gateway use, and no execute or Wwise startup. All Broker, exact-protocol, closed-request, no-direct-WAAPI, no-inline-code, no-unexpected-command, Skill/workspace integrity, and final-report gates passed. macOS used one-shot LaunchAgents; Windows used temporary active-desktop `InteractiveToken` / `Limited` Scheduled Tasks. Replays retained one attempt, started no Codex/Wwise work, and both hosts ended with zero scoped descendants, listeners, tasks, or launch resources. The earlier `imac-soundengine4-ea36a60-r6` immutable-harness-drift root and every historical FAIL/BLOCKED root remain frozen without replay or formal PASS credit. |
| #89 final CLI/Console deterministic gates | Exact final packaged-Skill candidate `c216f68fae945b493e2de71e59768a9a65aed7ab`: macOS Program passed 4519 / 2 platform skips, native-Windows Program passed 4501 / 20 platform skips, macOS Non-live passed 9757 / 111 skipped / 27 deselected, and the CLI/Console-focused regression passed 296 / 27 environment skips / 9572 deselected; every credited invocation exited 0. | All 65 five-version `generic-cli-console` rows are sealed by digest `3f5b7464510f32b6f06dc4c6c3e0a7da700159ad07b8aff69b4b759bed41b9e1`. Fourteen exact APIs expose only `cli-console-business/v1` declarations; Gateway owns native negative flags, platform mapping shape/order, isolated I/O roots, host/Wine paths, shell serialization, Preview, execute-once, and verification. Final review repairs require `ak.wwise.cli.migrate` to follow the returned verify continuation and disclose every closed scalar choice in the versioned input form instead of Markdown. Program, Non-live, and focused tests started neither Codex nor Wwise; skips receive no PASS credit. |
| #89 proportional dual-host real-Wwise proof | Packaged candidate `41d07ab` passed four isolated Wwise 2025.1 shapes on both macOS and native Windows: project verify, object dump, SoundBank generation, and project-open transition; each invocation reported 1 passed / 23 deselected. The same candidate passed isolated 2022.1 SoundBank generation on both hosts, each 1 / 23. Earlier exact test candidate `d7209b6` with packaged Skill `25bd39f` passed isolated 2022.1 project verify and object dump on both hosts, each 1 / 23. | Every credited invocation exited 0 against a disposable project. The final implementation maps Console project transitions across the Wine boundary, prefers filesystem project identity over hierarchy `path="\\"`, owns flat-versus-nested platform mappings, and isolates the pinned 2022 SampleProject's unavailable optional effects before generation. Source projects remained unchanged, passing sandboxes were removed, and scoped residual processes were empty. Earlier diagnostics that exposed post-exec project reads, mapping nesting, startup races, optional-plugin generation exits, or Wine verifier mismatches are frozen without PASS credit; a generated `.bnk` never overrides a nonzero WwiseConsole exit. |
| #89 final same-candidate cross-platform Fresh Agent proof | Exact final candidate `c216f68fae945b493e2de71e59768a9a65aed7ab`: macOS root `imac-cli-console-c216f68-r1` and native-Windows root `iwin-cli-console-c216f68-r1` each passed `cli_console_business_1` 1/1 fresh with `gpt-5.6-terra`, medium reasoning, default service tier, then passed identical `--resume --verify-only` audits. | Both fresh memory-off Agents selected the explicit `WwiseConsole 命令行` SoundBank route, copied the versioned closed scalar choices and complete declaration into one immutable Preview, and stopped without execute, Wwise, or mutation. All Broker, exact-protocol, closed-request, no-direct-WAAPI, no-inline-code, no-unexpected-command, integrity, and final-report gates passed. Windows used an active desktop Session 1 `InteractiveToken` / `Limited` Scheduled Task; the exported XML attested `InteractiveToken` while the registered Principal attested the omitted-default `Limited` value. The task and wrappers were removed, both replays started no Codex/Wwise work, and the final Windows scoped-process/task counts were zero. Frozen macOS root `imac-cli-console-03ebea9-r1` and native-Windows root `iwin-cli-console-dcd0bd0-r1` remain without replay or PASS credit; they record declaration-group ordering and ambiguous execution-channel diagnostics. Predecessor `d6d6709` Fresh passes are retained only as historical evidence because later packaged path/audit and review repairs changed the candidate. |
| #90 final host/UI/Debug deterministic gates | Exact final candidate `223d1fe5ace3cb7deebc269908902e1db8958043`: focused Host/UI/Debug, transaction, Wine-path, and semantic-profile regression passed 288; macOS Program passed 4526 / 2 platform skips; native-Windows Program passed 4503 / 25 platform skips; macOS Non-live passed 9818 / 111 skipped / 27 deselected. Every credited invocation exited 0. | All 15 exact `generic-host-ui-debug-waapi` rows are sealed by digest `8d701d66442416c74f627e468842139fa8971b441b9b813be95cd9e7d3712ee0`. The public `host-ui-debug-business/v1` and bounded `waapi-schema` read expose stable waveform, duration, level, channel, project-policy, include-examples, and exact artifact intent; Gateway owns versioned native fields, masks, marker structure, project flags, host boundaries, isolated I/O, Wine translation, Preview, project-transition settling, and verification. The final path matrix covers Windows-drive, UNC, traversal, mixed separators, case, spaces, Unicode, shell metacharacters, and audit drift. Program and Non-live started neither Codex nor Wwise; skips receive no PASS credit. |
| #90 proportional dual-host real-Wwise proof | Console candidate `0e6e00b309972a786275e963b28523e4b64e49d5`: macOS and native Windows Wwise 2025.1 each passed the schema plus Tone WAV workflow 2/2, and Wwise 2022.1 each passed the schema workflow 1/1. Authoring candidate `f1d16bb308e25f23390efbe01320562785ddd9d0`: macOS root `host-ui-debug-authoring-f1d16bb-mac-2022-r5` and native-Windows root `host-ui-debug-authoring-f1d16bb-win-2022-r1` each passed the exact 2022.1 project close/open transition 1/1. | Tone output was real 48 kHz, stereo, 16-bit WAVE_FORMAT_EXTENSIBLE PCM with about 1.15 seconds of frames. Both Authoring runs closed the sandbox, waited through Wwise's explicit transition lock, reopened the exact project, and verified its identity; macOS transiently translated the audited host path through the Wine drive. Windows ran in an active-desktop `InteractiveToken` / `Limited` task, which was removed. Both source-project full hashes and mtimes were unchanged, PASS sandboxes were deleted, and Wwise/task/8080 residual counts ended at zero. Final `223d1fe` only strengthens fail-closed canonical-target/audit validation for this same accepted path and adds its matrix; it does not change the credited native request or normal transition result, so these are proportional predecessor results rather than a same-candidate rerun claim. Frozen diagnostics and ordinary FAIL roots retain no PASS credit. |
| #90 cross-platform targeted Fresh Agent proof | Exact Agent-facing candidate `3c251496671cd673ab81d1930bf381c0e47a0d8e`: macOS root `imac-host-ui-debug-3c25149-r3` and native-Windows root `iwin-host-ui-debug-3c25149-r3` each passed `host_ui_debug_business_1` 1/1 fresh with `gpt-5.6-terra`, medium reasoning, default service tier, then passed identical `--resume --verify-only` audits. | Both fresh memory-off Agents copied the Gateway-owned Tone business continuation into one exact closed Preview and stopped without execute, mutation, or Wwise. Each used five commands and passed Broker, protocol, no-bypass, integrity, and final-report checks. Windows Fresh and replay used temporary active-desktop `InteractiveToken` / `Limited` tasks; both hosts removed launch resources and ended with zero scoped residuals. Later production commits add only deterministic project-transition settling and audited local-Wine path handling; they do not alter this offline Agent route, public Tone declaration, or Broker projection. Earlier unsupported-bit-depth and numeric-spelling roots remain frozen without replay or PASS credit. |
| #91 proportional dual-host real-Wwise Topic proof | Packaged runtime candidate `bb3f93593fcb03c2bff7378c01c1d7bd0127dc59`: macOS and native Windows Wwise 2022.1 each passed the targeted Topic business-input workflow `1 passed / 4 deselected`; both hosts' Wwise 2025.1 object-topic workflow passed `1 passed / 3 deselected`. Every credited invocation exited 0. | The 2022.1 workflow used stable business options and match facts while Gateway derived event paths, wire types, nesting, contract digest, and exact continuation; the publisher created a runner-owned object and the subscription matched its exact event before unsubscribe and cleanup. The 2025.1 workflow proves the adjacent real subscription/event lifecycle. Source projects remained unchanged, sandboxes were deleted, and scoped residual processes were empty. From `bb3f935` through final candidate `b29731e`, the packaged Skill differs only in frozen historical eval wording; Topic construction, dispatch, subscription, validation, and cleanup are identical. This is proportional host/version evidence, not a claim that every one of the 154 reflected Topic rows was fired on real Wwise. |
| #91 final same-candidate cross-platform wait/stream Fresh Agent proof | Exact final candidate `b29731e6cb84b5d9aa326227ffc1b4eb87edca9a`: macOS roots `imac-topic-b29731e-r7-typ21-repair` and `imac-topic-b29731e-r8-typ24-stream`, plus native-Windows roots `iwin-topic-b29731e-r5-typ21-repair` and `iwin-topic-b29731e-r4-typ24-stream`, each passed its one selected unit fresh and then passed an identical `--resume --verify-only` audit. | Each host has cumulative 2/2 targeted acceptance across two frozen roots, not one 2/2 root. TYP21 on Wwise 2021.1 rejected stale subscription knowledge, refreshed the current Topic business contract, waited for the exact three Windows SoundBank events, and verified Main_UI, Gameplay, and Ambience. TYP24 on Wwise 2024.1 selected the 30-second persistent stream, accepted exact Mac and Windows SoundBank events, emitted ordered started/event/terminal NDJSON with `duration_elapsed`, and unsubscribed cleanly. All Broker, publisher, event, archive, integrity, and final-report gates passed. Windows Fresh and replay used temporary active-desktop `InteractiveToken` / `Limited` Scheduled Tasks; all task/wrapper resources were removed and both roots ended with zero scoped descendants. Earlier macOS semantic FAIL or harness-BLOCKED roots remain frozen without replay or credit; they record result-scope, stream-classifier, lifecycle-audit, prompt-lint, and result-only SoundBank disclosure repairs. |
| #91 final deterministic and broad non-live gates | Exact packaged-Skill candidate `b29731e6cb84b5d9aa326227ffc1b4eb87edca9a`: focused interface-depth inventory 15 passed; Program 4528 passed / 2 platform skips; repaired full Non-live 9846 passed / 112 skipped / 27 deselected. Every credited invocation exited 0. | The generated inventory now contains zero migration ticket families and seals all 154 `generic-topics` rows with digest `48f62fffb957f2ed581bee75cb11ddd6624411b77fc307813d1984b5ce015982`; every Topic row is `already_deep`, has no leaked mechanics, and retains explicit audit evidence. The first full Non-live run exposed one stale expected protocol-step list after the final read-only SoundBank result disclosure; it completed 9845 passed / 1 failed, the exact five-case parameterized regression then passed 5/5 after updating that test-only expectation, and the complete clean rerun produced the credited 9846/112/27 result. Program and Non-live started neither Codex nor Wwise; declared skips receive no PASS credit. |
| #91 post-review closed Topic contract and gates | Exact packaged-Skill candidate `8d5499e704403411ef4dcb996839bf67246710ea`: macOS Program passed 4530 / 2 platform skips and full Non-live passed 9854 / 113 skipped / 27 deselected. Native-Windows Program passed 4507 / 25 platform skips. Later semantic-harness candidate `6d00e1eb9d7246e266fe9b5e59c10504b34f0150`, with the packaged Skill tree unchanged, passed full macOS Non-live 9855 / 113 skipped / 27 deselected; final disclosure-order successor `5355428904ce632cb805e5038593ba594daa99c1` passed the Topic-focused lane 438 / 29 environment skips / 9528 deselected. | Review repairs bind every live matrix wait to its current contract digest, require stream event ceilings, bound cumulative NDJSON bytes, report unsubscribe truth on cancellation, restore the frozen v2 suite exactly, and replace caller-authored wire-type words with contract-bound opaque `tvc1-*` semantic choices. The generated inventory still seals all 154 rows and zero migration families. A committed 24-family structural policy partitions the 2022.1/2025.1 union into active safe publishers, exact prerequisite boundaries, and a prohibited debug-assert boundary; blocked families receive no real PASS credit. |
| #91 post-review dual-host real-Wwise proof | Packaged candidate `8d5499e704403411ef4dcb996839bf67246710ea`: macOS Wwise 2022.1 and 2025.1 each passed the selected object/transport Topic live combination 1/1 and the selected audio/SoundBank/Switch destructive combination 3/3, for 8 credited tests. Native Windows passed the same two live tests 1/1 per version and the same two destructive groups 3/3 per version, also 8 credited tests. | Active families produced matching event payloads before unsubscribe and cleanup; source projects retained their hashes/mtimes and passing sandboxes were removed. The first Windows destructive command stopped before Wwise because the copied ignored config retained old-worktree absolute paths; after localizing only that candidate's ignored config, both unexecuted destructive lanes passed. This pre-launch configuration stop receives no failed-real-test credit. The packaged Skill is unchanged in later `6d00e1e` and `5355428` semantic-only commits. |
| #91 post-review Fresh Agent evidence and current Windows boundary | macOS root `imac-topic-6d00e1e-typ21-r1` passed TYP21 fresh plus identical verify-only; root `imac-topic-5355428-typ24-r1` passed TYP24 fresh plus identical verify-only. Both used `gpt-5.6-terra`, medium reasoning, and default service tier. Native-Windows roots `iwin-topic-8d5499e-typ21-r1` and `iwin-topic-6d00e1e-typ21-r1` are frozen BLOCKED without replay. | Mac TYP21 refreshed the stale contract and verified the three requested Windows events. Mac TYP24 accepted either order for the exact SoundBank entry/match disclosures, used a safe event ceiling greater than the two expected events, streamed for the full 30-second duration, verified distinct Mac/Windows payloads, and unsubscribed cleanly. Both Windows roots used attested `InteractiveToken` / `Limited` tasks but the standalone Codex ended with unfinished profile-free PowerShell `Get-Content` lifecycle items before any Gateway business dispatch; temporary tasks/wrappers were removed. These BLOCKED roots grant zero Windows Fresh PASS credit and do not replace the earlier `b29731e` historical 2/2 evidence. |
| #91 final post-review Fresh repair proof | Exact packaged-Skill candidate `8f2b0006da27a3a451538924f75a9b1b225c5e70`: macOS root `imac-topic-8f2b000-typ21-r1` and native-Windows root `iwin-topic-8f2b000-typ21-r1` each passed TYP21 fresh plus identical verify-only. Semantic-harness successor `f0c82da2ee20b6e324efaa33a19052a0e2437299`, whose packaged Skill tree is byte-identical to `8f2b000`, passed TYP24 fresh plus identical verify-only in macOS root `imac-topic-f0c82da-typ24-r1` and native-Windows root `iwin-topic-f0c82da-typ24-r2`. | TYP21 now discloses the platform exact-entry type before copying the opaque literal-text handle; the former Skill example that taught an untyped fact was removed and Gateway exposes a machine-readable `choice_on_disclosure` policy. TYP24 requires the SoundBank match disclosure and all four requested identity includes but no redundant result-entry disclosure; both final roots streamed for 30 seconds, verified distinct Mac/Windows events, and unsubscribed. Every source full hash and mtime stayed unchanged, PASS sandboxes were removed, and both replay audits started neither Codex nor Wwise. Windows Fresh/replay used attested `InteractiveToken` / `Limited` tasks; final independent checks found zero matching tasks, campaign processes, or Wwise processes. Earlier semantic FAIL and infrastructure-BLOCKED roots remain frozen without replay or credit. |
| #91 review-closure deterministic gates | Exact packaged-Skill candidate `d9a279cff9c825f2c04f2977fd6fddf06b69b547`: focused Topic/Gateway regression passed 431; macOS Program passed 4531 / 2 platform skips; native-Windows Program passed 4508 / 25 platform skips; macOS Non-live passed 9858 / 113 skipped / 27 deselected. Test-only unsubscribe-proof successor `1811342671220d1cba16fd86c0ccc74808b33789` passed the final focused structural/typed regression 34/34. Every credited invocation exited 0. | The final review repair gives exact-key nested Topic object/list members scope-bound opaque scalar choices, teaches the trusted inverse compiler to materialize open object/list containers, points the transport family to its exact-event test, and makes SoundBank structural-family evidence fail unless both the matching `generated` event and `generationDone` arrive. The test-only successor additionally requires the real subscription handler's `unsubscribe()` to return exactly `True`. Program and Non-live started neither Codex nor Wwise; declared skips receive no PASS credit. |
| #91 hard dual-host SoundBank Topic proof | Exact test-only successor `1811342671220d1cba16fd86c0ccc74808b33789`, whose packaged Skill tree is the exact `d9a279c` implementation: macOS and native Windows Wwise 2022.1 and 2025.1 each passed `test_soundbank_generate_write_to_disk_or_records_blocker` 1/1, for four credited invocations after unsubscribe enforcement. | Every credited run subscribed successfully before generation, required a `generated` payload naming the disposable SoundBank plus a separate `generationDone` payload, required `unsubscribe()` to return exactly `True`, wrote output only below the sandbox, preserved the source project hash/mtime and generated-output snapshot, removed the passing sandbox, and left no WwiseConsole process. The first earlier Windows diagnostic used an incomplete Python lacking `waapi-client` and timed out before any WAAPI probe; it receives no real-test credit. Both credited Windows reruns used one complete locked Poetry developer interpreter directly over SSH, not Task Scheduler or Fresh Codex. |
| #91 final review-closure dual-host Fresh proof | Exact Git candidate `70506bb23fa7f87cf35a2a09b0cb9145945778bf`, whose packaged Skill tree is the exact `d9a279c` implementation: macOS root `imac-topic-70506bb-final-r1` passed TYP21 and TYP24 together 2/2 fresh plus identical verify-only. Native-Windows root `iwin-topic-70506bb-typ24-r2` passed TYP24 fresh plus verify-only, and root `iwin-topic-70506bb-typ21-r3` independently passed TYP21 fresh plus verify-only. | Every credited run used `gpt-5.6-terra`, medium reasoning, and the default service tier. TYP21 refreshed the stale contract and verified the exact three Windows SoundBank events; TYP24 streamed for 30 seconds and verified distinct Mac/Windows events with complete identity fields. Mac used one one-shot LaunchAgent; Windows Fresh and replay used active-desktop `InteractiveToken` / `Limited` tasks. Replays started neither Codex nor Wwise. Source hashes/mtimes remained unchanged, PASS sandboxes were removed, tasks/wrappers were removed, and final Windows checks found zero matching tasks, scoped processes, or WwiseConsole processes. Windows mixed root `iwin-topic-70506bb-final-r1` remains frozen without replay: TYP21 passed, but TYP24 received two `CreateProcessAsUserW 267` failures before the match disclosure, performed only the initial schema command, and was strictly recorded as semantic FAIL with a pre-Broker infrastructure precursor. It grants no final TYP24 credit and was replaced only by the new targeted root after a clean desktop/process preflight. |
| #58 frozen deterministic full-surface candidate | Exact frozen candidate `af0cd28b63b13955b4f765c496a4d031b42bbeb9`: macOS Program passed 4532 / 2 platform skips; native-Windows Program passed 4509 / 25 platform skips; macOS Non-live passed 9860 / 113 skipped / 27 deselected; the focused release/compiler/handle/Preview/continuation/transaction/Topic/file/Lua/security gate passed 514/514. Every invocation exited 0. | The generated full-surface report covers all 824 five-version lanes (670 function and 154 Topic) with 824 construction continuations and zero duplicate, missing, unexpected, host-overlay, semantic-overlay, unknown-keyword, or unresolved-reference findings. The depth inventory covers 824 native plus 153 operation lanes with zero migration families and zero unowned rows. `compileall`, both generated-report `--check` commands, `git diff --check`, and clean-worktree scope passed. Public-route, removed shallow-input, weaker-generic-bypass, immutable Preview, archive/replay, verifier, cleanup, and exact-artifact negatives are included in the fixed/focused gates. Program and Non-live started neither Wwise nor Fresh Codex; declared skips receive no PASS credit. This candidate is the frozen input to #59 and #60; the evidence-only successor does not replace it. |
| #59 frozen deep-interface dual-host real-Wwise gate | Packaged Skill candidate `af0cd28b63b13955b4f765c496a4d031b42bbeb9`, with byte-identical packaged Skill through final test/harness candidate `a09607f360defba2d78708890217cf9a8fe13295`: macOS and native Windows each passed 14 isolated Wwise 2022.1 Console/destructive nodes, 19 isolated Wwise 2025.1 Console/destructive nodes, and four current-candidate read-query/Topic live nodes. Current-candidate Authoring then passed 3/3 on Wwise 2022.1 and 2/2 on Wwise 2025.1 on each host; the 2025.1 project close/open sample was the same explicit version skip on both hosts and receives no PASS credit. | The real set covers multi-item `audio.import` in one immutable Preview, type/path normalization, metadata handles, dependency and ordered compound execution, object topology and relationships, SoundBank/file artifacts, media reads, Core/project settings, runtime controls, UI capture/execute/register/unregister, SoundEngine runtime/spatial effects, CLI/Console, exact tabular and Lua artifacts, fixed business query, and actual Topic events. Console-only Authoring/SoundEngine rows remain explicit host boundaries; CLI Lua records its one non-retry indeterminate host boundary and does not receive effect credit. All credited invocations exited 0, source full hashes and project mtimes stayed unchanged, passing sandboxes were deleted, macOS Wwise/8080 state was cleared, and Windows `InteractiveToken` / `Limited` Authoring tasks were removed with zero new Wwise residuals. Frozen diagnostics receive no credit: the first 2025.1 save helper used a retired continuation shape, the first macOS CLI-Lua restart raced the old port release, and Windows Authoring r1 escaped its added pytest paths before collection. The repaired helper follows `project.save` Business Draft continuation, waits boundedly for exact-port release, and records both incidents in `tests/AGENTS.md`. Deliberate crash/assert/restart routes were not executed. |
| #59 review-closure deterministic gates | Exact evidence candidate `3879b309032f70d12870d6110507d392e1aa6b16`, whose packaged Skill is byte-identical to `af0cd28`: macOS Program passed 4532 / 2 platform skips; native-Windows Program passed 4509 / 25 platform skips; macOS Non-live passed 9862 / 113 skipped / 27 deselected; the complete sandbox-fixture focused file passed 33/33 on each host. Every invocation exited 0. | The two additional Non-live passes over #58 are the bounded exact-port release tests. `py_compile`, `git diff --check`, source-scope comparison, and tracked worktree cleanliness passed. Program and Non-live started neither Wwise nor Fresh Codex; declared skips receive no PASS credit. This documentation successor does not replace the frozen packaged Skill or any real-host result. |
| #59 post-review exact v2 dual-host proof | Exact test/evidence candidate `7f8d0810c87696e1ff1df7e1e3f12255b5e7f406`, whose packaged Skill remains byte-identical to `af0cd28`: macOS and native Windows Wwise 2022.1 and 2025.1 each passed the same five repaired nodes, `5 passed / 21 deselected`, for 20 credited invocations. The nodes were object lifecycle, exact Topic/create/unsubscribe cleanup, closed audio-import/SoundBank/Switch workflows, exact tab import, and object graph/plug-in/bulk-set/RTPC. | Every host/version emitted two `waapi-skill.host-category-evidence/v2` records: seven transaction-fixture transactions ended `verified`; the 36 workflow transactions ended 34 `verified` plus the same two explicit `result_schema_checked` boundaries. The records retain every transaction ID/hash/state/event sequence, exact selected node IDs, source project/hash/mtime ns, sandbox path, quarantine path, cleanup details, and residual process list in `.waapi-skill-state/evidence/full-typed-input/{macos,windows}-category-evidence.jsonl`. Exact execution envelopes in Unix ns were Mac 2022 `1788107702399761000..1788107723270298000`, Mac 2025 `1788107724355694000..1788107747772627000`, Windows 2022 `1788107705323487100..1788107800650599600`, and Windows 2025 `1788107814668033000..1788107961018714400`: the hosts overlapped while versions were sequential per host. Source hashes stayed `fbc080432115e775f98b929c46d1a48390ee29e9e82c90778fff51e1f1f38964` for 2022.1 and `9052fe4d1fe4d193d98af7c989821b1697e93f7fd33728dbd18c16a4e5aef584` for 2025.1; exact before/after project mtimes matched on all four lanes. Passing sandboxes were deleted and every residual list was empty. |
| #59 post-review closure gates | Exact candidate `7f8d0810c87696e1ff1df7e1e3f12255b5e7f406`: the evidence/sandbox focused files passed 41/41 on macOS and native Windows; macOS Program passed 4532 / 2 platform skips; native-Windows Program passed 4509 / 25 platform skips; macOS Non-live passed 9866 / 113 skipped / 27 deselected. Every credited invocation exited 0. | The four Non-live additions over `3879b30` are the new exact-evidence and unconditional failure-quarantine regressions. Failed real modules now preserve their sandbox unconditionally, rather than depending on `WWISE_SANDBOX_KEEP_ON_FAILURE`; v2 rows distinguish deleted, quarantined, and retained paths. Real fixtures use `query-object --exact-id`, repeated closed `--path-segment`, default identity outputs, and business `--include` fields; retired `--object-id`, raw `--path`, `--return-field`, local Wwise-path parsing, and the retired 2025.1 save prefix are prohibited in `tests/AGENTS.md`. Program and Non-live started neither Codex nor Wwise. |
| #59 final two-phase exact dual-host category proof | Exact test/evidence candidate `5668cb2c5673bc802142bcf1d679e55a2e911ea6`, whose packaged Skill remains byte-identical to `af0cd28`: macOS and native Windows each passed 14 isolated Wwise 2022.1 workflow nodes and 19 isolated Wwise 2025.1 workflow nodes, for 33/33 per host and 66 credited real invocations. Every node ran in its own pytest process and Wwise lifecycle; every invocation exited 0. | Each host retained 66 v3 rows: 33 `prepared/PENDING` rows with no credit followed by 33 `final/PASS` rows. Per host the exact transaction ledger contains 141 `verified`, 19 explicit `result_schema_checked`, two non-retry `indeterminate`, and two deliberate fixture `execution_cancelled` outcomes; every transaction ID, artifact hash, event sequence, selected node, node outcome, source hash/mtime ns, sandbox/quarantine path, cleanup result, and residual process list is retained locally in `.waapi-skill-state/evidence/full-typed-input/{macos,windows}-category-evidence.jsonl`. All final-PASS source hashes and mtimes matched, all passing quarantines were released, and every residual list was empty. Mac envelopes were 2022.1 `1788109574640891000..1788109656536248000` and 2025.1 `1788109657302191000..1788109769543599000`; Windows envelopes were 2022.1 `1788109570780717900..1788109977344258000` and 2025.1 `1788109979360427200..1788110528449744300`, proving host overlap and per-host version sequencing. |
| #59 frozen shared-host scheduling diagnostics | Candidate `4c7ac7557d1ed2065ef7f84bc1dd57bceb079f9c`: one full-module Wwise 2022.1 diagnostic on each host passed the categories before `ak.wwise.cli.verify`, then that terminal CLI operation ended the shared WAAPI lifecycle and contaminated later nodes. Mac recorded 12 PASS / 9 FAIL / 5 version skips; Windows recorded the same. These roots grant no category PASS credit and were not replayed. | The v3 final rows record every node separately as PASS, FAIL, or SKIP and preserve the failed workflow sandboxes at `sample-project-bdc4886afb024876936072a302b2eacb` on macOS and `sample-project-a6c952f0a3fa46c9952466d792eda603` on Windows. The subsequent isolated campaign passed `cli.verify`, dump, generate, and every formerly contaminated node on both hosts, proving a scheduling/lifecycle fault rather than nine product regressions. `tests/AGENTS.md` now prohibits full-module category campaigns across terminal CLI ownership boundaries. |
| #59 final review-closure gates | Exact broad-gate candidate `5668cb2c5673bc802142bcf1d679e55a2e911ea6`: the shared v3 evidence/quarantine focused files passed 45/45 on macOS and native Windows; macOS Program passed 4532 / 2 platform skips; native-Windows Program passed 4509 / 25 platform skips; macOS Non-live passed 9870 / 113 skipped / 27 deselected. Test-only quarantine-truth successor `020a21b` then passed the expanded focused files 47/47 on both hosts. Every credited invocation exited 0. | The shared finalizer captures exact pytest phase outcomes, never promotes skip/blocked to PASS, materializes transaction outcomes before cleanup, releases the live lock before classification, moves every sandbox into quarantine before evidence finalization, and requires `prepared/PENDING -> final/PASS`. The successor derives `quarantined`, `retained`, or `quarantine_failed` from observed filesystem state and the v3 validator rejects a quarantine claim without an exact path. Evidence-write or cleanup failures retain a non-PASS boundary. Program and Non-live started neither Codex nor Wwise. |
| #60 final deep-business deterministic gates | Exact packaged-Skill candidate `483ca817bbc7ab2404e1f96537f55195629223b9`: macOS Program passed 4574 / 2 platform skips and native-Windows Program passed 4551 / 25 platform skips. Semantic-harness successor `5f53ed828574e408000d96b738422e075895e846`, whose packaged Skill tree is unchanged, passed focused Campaign/archive validation 202/202 and full macOS Non-live 10049 / 113 skipped / 27 deselected. Every credited invocation exited 0. | The Gateway operation catalog now provides exact route-selection guidance for Authoring UI, single-reference, and WwiseConsole SoundBank intent; natural-language business tasks begin with one required `operations` read. Named project-setting and SoundEngine option groups are transport-order independent, the deep API profile delegates the one-time introduction prose check to its dedicated profile, and exact safe parent preflights remain bounded. Program and Non-live started neither Codex nor Wwise; declared skips receive no PASS credit. |
| #60 dual-host full-profile and failed-first Fresh evidence | Exact packaged-Skill candidate `322af149de30d701c4da0c1a07e2e4dee8163ef3` full roots `imac-m60-322af14-r45-deep19` and `iwin-m60-322af14-r45-deep19` attempted all 19 units with raw harness results 13/19 and 15/19. Business-result review reclassified only proven oracle false negatives, yielding 17/19 on each host; it did not promote wrong routes or missing Gateway work. Later packaged candidate `483ca817` made `operations` discovery mandatory and retained the same public business surface through semantic-only successor `5f53ed8`. | The four r45 real failures were retested first, not hidden by a new broad run. Mac root `imac-m60-d6716d0-r47-fail4` produced matrix PASS for AUI and Topic 2/2; Windows root `iwin-m60-d6716d0-r47-fail4` produced matrix PASS for Reference and CLI 2/2. Their Campaign wrappers were frozen BLOCKED because the outer archive schema omitted deep-wrapper metadata; neither root is reported as a Campaign pass. Mac root `imac-m60-8485895-r48-fail4` then passed Topic and structurally passed AUI, whose sole literal-command marker failure was corrected as an oracle defect. Windows r48 passed Reference while CLI stopped before Gateway on `CreateProcessAsUserW 267`; it grants no CLI credit. Final macOS root `imac-m60-5f53ed8-r50-aui` passed AUI 1/1 as both matrix and Campaign and then passed identical `--resume --verify-only`. Thus every one of the 19 fixed profile units has same-host passing evidence on the unchanged packaged Skill, cumulatively across frozen roots; no root is claimed as a single-root 19/19 result. |
| #60 launch, integrity, and cleanup boundary | Every Fresh task used `gpt-5.6-terra`, medium reasoning, default service tier, memory disabled, one packaged Skill, and a fresh Codex process/thread/task. macOS formal roots used one-shot LaunchAgents with `RunAtLoad=true` and `KeepAlive=false`. Native Windows used the active desktop user in Session 1 through temporary Task Scheduler principals attested as cmdlet `Interactive` / XML `InteractiveToken` semantics and `Limited`; SSH only registered, started, waited, read evidence, and deleted tasks. | All PASS paths stopped at immutable Preview or bounded read/Topic completion; no Fresh mutation executed. Passing Topic evidence retained exact terminal events and unsubscribe cleanup. Source-project hashes/mtimes remained unchanged where Wwise ran; passing sandboxes were removed, failed/blocked roots stayed sealed, and final scoped checks found no matching LaunchAgent, Scheduled Task, campaign process, Wwise process, or owned wrapper. Pre-root environment stops, prompt-lint BLOCKED roots, archive-schema BLOCKED roots, literal-marker false failures, and the r48 Windows 267 root remain explicit and receive no formal Campaign PASS credit. |
| #60 final closure deterministic gates | Exact packaged-Skill candidate `ce06b255623eac26c4d84063453a0b1f553463e4`: macOS Program passed 4671 / 2 platform skips; native-Windows Program passed 4648 / 25 platform skips; macOS Non-live passed 10242 / 113 skipped / 27 deselected. Semantic-oracle successor `82530a91cb1f2a8d57bb3f5504b53b3e062cd2df`, whose packaged Skill tree remains digest `9f37e9992a6c4791f07536caafaf791b8bebbf3473fb2ca076197b9bb939dc18`, passed the focused Broker/object-metadata/protocol gate 560 / 4 native-Windows skips and macOS Program 4671 / 2 platform skips. Every credited invocation exited 0. | The lifecycle declaration no longer accepts model-authored object or parent handles: the Draft retains its bound roles and the Gateway derives those handles internally. Compact `operations.routing_precedence` returns the exact reflected WwiseConsole SoundBank route. The release audit explicitly proves empty-scalar copy/delete/move declarations remain deep while `object_handle` and `parent_handle` are absent. The first broad attempts exposed only stale generated/audit expectations; after updating those derived tests, the complete Program and Non-live reruns were green. Program and Non-live started neither Codex nor Wwise; declared skips receive no PASS credit. |
| #60 final r72-r74 dual-host Fresh closure | On `ce06b25`, macOS root `imac-m60-ce06b25-r72-fail3` and native-Windows root `iwin-m60-ce06b25-r72-fail3` each passed the previous SoundBank/CUB/CLI failure set 3/3 fresh plus identical verify-only. Full roots then attempted all 19 units: `imac-m60-ce06b25-r73-deep19` passed 18 and failed only OMB, while `iwin-m60-ce06b25-r73-deep19` passed 19/19 in one root plus identical verify-only. The Mac OMB failure was a Broker false negative: the Agent supplied the sole correct but redundant `--role object`; Gateway and business identity were otherwise unchanged. On harness-only successor `82530a9`, roots `imac-m60-82530a9-r74-omb` and `iwin-m60-82530a9-r74-omb` each passed OMB 1/1 fresh plus identical verify-only. | Mac therefore has same-packaged-Skill passing evidence for all 19 unique units cumulatively across r73 and r74, not a claimed single-root 19/19. Windows has both the r73 single-root 19/19 result and the final-oracle OMB replay. The oracle correction accepts only the exact redundant `object` role when the sealed protocol has no role flag; wrong, parent, duplicate, and multi-role forms remain fail-closed, and the executed argv remains unchanged. The Mac r73 FAIL root is frozen without replay. |
| #60 final launch, integrity, and cleanup proof | Every r72-r74 Fresh task used `gpt-5.6-terra`, medium reasoning, default service tier, memory disabled, one packaged Skill, and a fresh Codex process/thread/task. macOS used one-shot `RunAtLoad=true`, `KeepAlive=false` LaunchAgents. Native Windows used the active desktop user in Session 1 with XML-attested `InteractiveToken` and `Limited` temporary Scheduled Tasks; SSH only copied launch resources, started, waited, and read results. | All passing roots and replays returned 0. Windows controller evidence reported one attempt manifest, zero descendants, and removed each task; macOS LaunchAgents were booted out and removed after their one run. Passing paths stopped at Preview or bounded read/Topic completion, source projects remained unchanged, passing sandboxes were removed, the failed Mac r73 sandbox remained sealed, and final scoped checks found no matching campaign, Codex, Wwise, LaunchAgent, or Scheduled Task residual. |
| Final #51 public `integration` roots on exact candidate `ebcfde245bcbcacd2b8842e5ec205e7111b86743` | macOS `imac-int-ebcfde2-r67-full12`: 12 passed / 0 failed plus identical verify-only; native Windows `iwin-int-ebcfde2-r56-full12`: 12 passed / 0 failed plus identical verify-only | Both hosts ran the complete public profile in one immutable root: Weather, Alarm, Harbor, Rifle, Footsteps, and Weapons on Wwise 2022.1 and 2025.1. All 24 lifecycle records report PASS, unchanged source full hash and project mtime, removed PASS sandboxes, and no lifecycle errors. Final scoped-process checks were empty; the one-shot macOS LaunchAgent and Windows `InteractiveToken` / `Limited` Scheduled Tasks were deleted. This is independent single-root 12/12 acceptance on both hosts, not cumulative or cross-host credit. |
| Final #51 pre-integration review-repair gates on exact code candidate `170e8e8f01cd5e931933c6fe76baff47d0683f57` | macOS Program 4737 passed / 2 skipped; native-Windows Program 4714 passed / 25 skipped; macOS Non-live 10322 passed, 113 skipped, 27 deselected; all exit 0 | The review repair retains grouped import row-order compatibility and identity-aligned `object.set` witness comparison, gives playing and transport capability stores the same Windows reparse-point rejection already used by game-object handles, and resolves non-stable `--field` batch names through the existing live metadata path. Focused handle/filesystem regression passed 32/32 after an eight-failure TDD red phase; the Weather/Gateway/Broker regression passed 590 / 8 platform skips after a three-failure red phase, with an additional stable-field contradiction negative. Program and Non-live started neither Codex nor Wwise; declared platform/live skips receive no PASS credit. |
| Final #51 Weapons batch-order repair gates on exact code candidate `fd2f9ed2c9fd2336e76545b1aef6f0ce4e99acfe` | macOS Program 4738 passed / 2 skipped; native-Windows Program 4715 passed / 25 skipped; macOS Non-live 10325 passed, 113 skipped, 27 deselected; focused object-set batch/Gateway/Broker regression 14/14; all exit 0 | Frozen exact-candidate roots `imac-int-2e60bce-r69-full12` and `iwin-int-2e60bce-r60-full12` each passed ten units and failed only INT22/INT25 Weapons before Gateway because the Broker compared commutative repeated-option placement literally. All four failures had the same argument-14 rejection; the source hashes/mtimes were unchanged and failed sandboxes were retained. The repair derives stable object-set fields from the operation contract, avoids rewriting an unchanged handle registry, and canonicalizes independent batch groups while checking every object, field, handle, and value. Its initially strict row-sequence oracle was superseded by the final semantic-harness correction below. Program and Non-live started neither Codex nor Wwise; declared platform/live skips receive no PASS credit. |
| Final #51 independent-row oracle and public integration closure on exact candidate `0682c1a979f7ce5bfb648914914b7393148a6495` | Focused independent-row/Weapons regression passed 14/14. Native Windows root `iwin-int-0682c1a-r63-full12` passed 12/12 in one root plus identical verify-only. MacOS root `imac-int-0682c1a-r73-full12` passed 11/12; queued root `imac-int-0682c1a-r74-int22-rifle` passed the sole failed unit plus identical verify-only. | The packaged Skill tree is byte-identical to `0edaf1a`. Independent existing-object edits may be permuted, while missing, extra, duplicate, or changed rows and facts still fail closed; ordered create/import semantics are unchanged. The Mac failure was an Agent-only early stop after falsely calling `response_integrity.complete=true, truncated=false` truncated, so no code or harness change preceded the queued rerun. MacOS therefore has explicitly cumulative same-candidate 12/12 evidence, not a single-root claim; Windows has a single-root 12/12. Across 25 lifecycle records source hashes/mtimes were unchanged, PASS sandboxes were removed, the failed sandbox remained sealed, verify-only replays exited 0, and final LaunchAgent/Scheduled Task/Wwise checks were empty. |
| Post-audit transaction execution-lease gates | Exact product candidate `4dadee360c736c18a7c616dd8f67a2ea31be1f00`: focused concurrency/lease regression passed 5/5 on macOS and native Windows; macOS Program passed 4743 / 2 platform skips; native-Windows Program passed 4720 / 25 platform skips. Test-only manifest-count successor `f17554acbd065f8d7cc25cea4afdf423d653b511` passed the exact self-check 1/1 on both hosts and full macOS Non-live 10330 / 113 skipped / 27 deselected. Every credited invocation exited 0. | A deterministic red test first reproduced the defect: while one fake WAAPI call held a transaction in `executing`, a concurrent verify changed it to `indeterminate`. The fix adds a separate non-blocking, cross-process execution lease held across validation, dispatch, and result persistence. A contender returns `execution_in_progress` without changing durable state; only a caller that acquires the lease and still observes `executing` may perform stale-owner recovery. Tests cover active execute versus verify, abandoned-state recovery without replay, successful execution followed by rejected re-execution, POSIX ownership/release, and real native-Windows `msvcrt` contention/release. The first Non-live run passed 10329 tests and exposed only the stale 180-node manifest expectation; after changing it to the measured 182 nodes, the focused check and complete rerun passed. Program and Non-live started neither Codex nor Wwise, so no Fresh Agent or real-Wwise evidence is claimed. |

## Archived steering evidence

The following records preserve historical statements moved from always-loaded
agent guidance at `cba4eefb`. Their original candidates, failures and cumulative
qualifications remain unchanged. They grant no evidence to later candidates.

### Historical steering record: `AGENTS.md` lines 479–669 at `cba4eefb`

Pre-review public `integration` candidate
`ebcfde245bcbcacd2b8842e5ec205e7111b86743` passed all 12 units in one fresh
root on each host: macOS `imac-int-ebcfde2-r67-full12` and native Windows
`iwin-int-ebcfde2-r56-full12`. Both roots then passed identical
`--resume --verify-only`. Across the 24 PASS lifecycle records, source-project
full hashes and mtimes remained unchanged, passing sandboxes were removed, and
final scoped-process checks were empty. The macOS LaunchAgent and Windows
`InteractiveToken` / `Limited` Scheduled Tasks were deleted. This is
independent single-root 12/12 evidence on both hosts, not cumulative repair-root
credit. Review-repair code candidate
`170e8e8f01cd5e931933c6fe76baff47d0683f57` later hardened playing and
transport capability stores against Windows reparse points and resolved
non-stable object-set batch `--field` names through live metadata, so the
earlier root remains truthful evidence but is not final-candidate acceptance
for that successor. That successor passed macOS Program 4737 / 2 skipped,
native Windows Program 4714 / 25 skipped, and macOS Non-live 10322 / 113
skipped / 27 deselected. Batch-order repair candidate
`fd2f9ed2c9fd2336e76545b1aef6f0ce4e99acfe` then passed macOS Program 4738 /
2 skipped, native Windows Program 4715 / 25 skipped, and macOS Non-live 10325 /
113 skipped / 27 deselected before its targeted Weapons reruns.

Final semantic-harness candidate
`0682c1a979f7ce5bfb648914914b7393148a6495` keeps the packaged Skill tree
byte-identical to `0edaf1a` and accepts permutations of independent existing-
object edit rows while still rejecting missing, extra, duplicate, or changed
objects, fields, handles, and values. Native-Windows root
`iwin-int-0682c1a-r63-full12` passed the public `integration` profile 12/12 in
one root plus identical verify-only. MacOS root
`imac-int-0682c1a-r73-full12` passed 11/12; only INT22 Rifle stopped before
Preview after the Agent incorrectly called an explicit
`complete=true, truncated=false` response truncated. Fresh queued root
`imac-int-0682c1a-r74-int22-rifle` then passed that sole unit plus identical
verify-only without any code, suite, harness, or option change. MacOS therefore
has same-candidate cumulative 12/12 evidence, not a single-root 12/12 claim.
Every source hash and project mtime remained unchanged, passing sandboxes were
removed, the failed sandbox stayed sealed, and all temporary LaunchAgents,
Scheduled Tasks, and Wwise processes were cleared.

Composer migration evidence is focused Adapter evidence, not public
`integration` acceptance. For `object.set`, candidate
`68697244063e02304eea79da54da502270be3704` passed Weather and Weapons on
Wwise 2022.1/2025.1 in both macOS root `imac-flatrow-6869724-r1` and
native-Windows root `i15-6869724-r1`; both four-unit roots also passed
identical `--resume --verify-only` audits. For `audio.import`, macOS root
`imac-import-6479595-r13-final6` at
`6479595ea4b9a53c3351a4d1595c988e94ee5967` passed all six selected
Weather/Rifle/Footsteps version units fresh and verify-only. Native-Windows
root `iwin-import-f87b800-r2-interactive` passed four and failed two;
`iwin-import-0be8266-r3-rifle-footsteps` then passed Footsteps and failed
Rifle, and final fresh root `iwin-import-0be8266-r4-rifle` passed Rifle and
its identical verify-only audit. The commits after `6479595` changed only
program/semantic tests and harness support, not the packaged Skill tree. Thus
all six Windows audio-import units have passing evidence cumulatively across
three frozen roots, not one root or one Git candidate with a 6/6 result. Every
recorded source hash/mtime stayed unchanged; PASS sandboxes were removed, FAIL
sandboxes were sealed/quarantined, and scoped residual-process checks were
empty.

For Switch assignments, runtime candidate
`d05f1ecdc3b33fca83866e75669c65039877edd6` passed the final macOS and
native-Windows Program gates, macOS Non-live, and the closed add/remove
workflow on native Windows Wwise 2022.1/2025.1. Route-only candidate
`d45f75f5e75190d5b4e607a02aee2dcf38e73ab9` then passed macOS Program and
the same real workflow on macOS 2022.1/2025.1. Fresh roots
`imac-sab-d45f75f-r2` and `iwin-sab-d45f75f-r2` each passed the one-unit
`switch_assignment_business_1` profile plus identical
`--resume --verify-only`. Earlier `d05f1ec` roots on both hosts remain
frozen FAILs because the Agents invented operation aliases; the Broker rejected
them before Gateway or Wwise dispatch. No Fresh root executed a mutation, all
temporary launch resources were removed, and scoped residual-process checks
were empty.
After the entry Skill was compacted, exact packaged-Skill candidate
`b544197fb6b7455814fbb2079043a5a354daca59` repeated the same one-unit PASS
plus identical verify-only in macOS root `imac-sab-b544197-r1` and
native-Windows root `iwin-sab-b544197-r1`. Both roots retained sealed attempt
manifests, started no Wwise process, executed no mutation, removed their
temporary launch resources, and ended with zero scoped residual processes.

Final deepened Switch-assignment candidate
`c874917220cb7723d60f86a14cea72c5d15cca52` passed the one-unit profile
fresh plus identical `--resume --verify-only` in macOS root
`imac-sab-c874917-r1` and native-Windows root `iwin-sab-c874917-r1`.
Both Agents followed the Gateway-owned copy-ready `draft-start`, then the fixed
`switch_container`, `child`, and `state_or_switch` role continuations into one
Preview; no Wwise process or mutation occurred. The Windows Fresh and replay
used temporary `InteractiveToken`/`Limited` Scheduled Tasks. Both hosts ended
with zero scoped residual processes and Windows retained zero matching tasks.
Exact Program candidate `4c55ba6b53eeb4beff97e7b590686d78da7e612e`
passed macOS 3659 / 2 skipped and native Windows 3646 / 15 skipped; later
`c874917` changes only semantic evidence/protocol tests. MacOS Non-live at
`d10dc23c4dd95eb865a5a768ac8a4e0885e6a233` passed 8639 / 110 skipped /
27 deselected. The later packaged diffs are bounded to copy-ready business
start/role continuations and compact audio-import receipts, covered by exact
focused regressions (410 passed at `4389b6c`, 452 / 4 skipped at `4c55ba6`,
and 76 passed at `c874917`); Switch native dispatch and verification did not
change. Frozen Mac diagnostic root `imac-sab-d10dc23-r1` stopped after a
successful schema read without issuing `draft-start`, received no PASS credit,
and was not replayed.

The completed 2026-07-31 macOS integration evidence is cumulative across frozen
campaign roots, not one final-candidate 6/6 run. The initial `a12` root passed
both Alarm and Harbor workflows on both versions and failed both Weather
workflows. Fresh repaired roots `a20-int22-weather` and
`a24-int25-weather` then passed the two Weather units. Thus all six unique
profile units have passing evidence across those roots; do not report that
`a12` itself passed 6/6 or that all six were rerun after the final repair.
Every passing sandbox was removed, failed sandboxes were sealed and
quarantined, and both source SampleProjects retained identical full hashes and
mtimes. This older evidence belongs to the candidate before the
structured-query request and closed mutation-selector migration.
The roots named in this paragraph and the 2026-08-03 macOS paragraph below
seal `runtime.platform=darwin`; later cross-host component reruns are recorded
separately.

The 2026-08-03 current-wording rerun is also cumulative, not one final-candidate
6/6 run. `campaign-integration-workflows-v1-terra-20260803-current-r1` passed
five units and failed `INT25-ALARM-DIAGNOSE-AND-REPAIR` before mutation because
the Agent redundantly re-read the Action instead of following the already
returned `Target.id`. The Skill query reference was then narrowed to forbid
that duplicate hop. Fresh roots `r2-int25-alarm-action-hop` and
`r3-int22-alarm-action-hop` passed both Alarm versions on the same repaired
candidate, and both passed `--resume --verify-only`. Weather and Harbor had
loaded only the unchanged operate reference in `r1`; all four passed there.
Thus all six current prompt units have passing evidence across these roots,
but there is still no single repaired-candidate 6/6 campaign. All eight
recorded lifecycles preserved source hashes and mtimes; passing sandboxes were
removed and the one failed sandbox remains quarantined. Those V1 roots do not
validate the newer V2 fixture, routing, or workflow contracts.

Later reruns used the legacy internal
`integration_workflows_cross_version_6` component, not the public composed
`integration` profile. At commit
`9e75a1aea496abcb9ef2a61e1da685adb99f4b01`, macOS root
`imac-wah-9e75a1a-r1` passed all six component units fresh and then passed
`--resume --verify-only`. At commit
`9b4de8f618855091a424700b50ab8b0fd1989270`, macOS root
`imac-wah-9b4de8f-r1` passed five units and failed one, while native-Windows
root `iwin-wah-9b4de8f-r1` passed three and failed three; both failed roots
were frozen without verify-only replay. These results remain exact
six-unit-component provenance and must not be reported as current public
`integration` acceptance or combined into a unified 12/12 result.

### Historical steering record: `AGENTS.md` lines 686–706 at `cba4eefb`

The completed 2026-08-03 macOS evidence for that legacy component is
cumulative across frozen roots, not one final-candidate 6/6 run. `r8` passed
both Rifle units, `r12-2022` passed the
2022.1 Weapons unit, `r23-2022-footsteps` passed the 2022.1 Footsteps unit, and
`r24-2025-repairs` passed the 2025.1 Footsteps and Weapons units. Thus all six
unique units have passing evidence across those roots. Passing sandboxes were
removed; failed or blocked diagnostic sandboxes were sealed and quarantined;
every recorded source-project full hash and mtime remained unchanged. This
grants no per-API coverage credit and proves only the exact Rifle, Footsteps,
and Weapons workflow paths, not advanced WAQL or unrelated routes.

The later native-Windows evidence for that legacy component is also cumulative.
At commit `0dfea2b`,
`windows-v2-six-0dfea2b-r1` attempted all six units, passed 2022.1 Rifle,
2022.1 Footsteps, and 2025.1 Rifle, failed the other three, exited `1`, and had
no verify-only replay. At `a516835`, `a516-w22-r1` passed 2022.1 Weapons fresh
and verify-only; `a516-f25-r1` failed 2025.1 Footsteps and was frozen without
verify-only. At `f1b6a51`, `f1b-f25-r1` and `f1b-w25-r1` passed 2025.1
Footsteps and Weapons fresh and verify-only. All six V2 units therefore have
native-Windows passing evidence across these frozen roots, but there is no
single-root or single-candidate Windows 6/6 result.

### Historical steering record: `tests/AGENTS.md` lines 544–554 at `cba4eefb`

The focused `modification_policy_9` campaign is separate from those historical
v2 totals. Its sealed
`campaign-modification-policy-9-c7` run passed 9/9 Wwise 2022.1 tasks and all
15 turns using nine unique memory-isolated Codex Terra threads. It covered
three repetitions each of `read_only`, question-style `ask_before_changes`,
and same-turn `allow_changes`; all source-project hashes remained unchanged
and every sandbox was cleaned. The six authorized writes each verified seven
created objects through 46 passing business assertions. Preserve this exact
scope: it is policy-interaction evidence for that frozen c7 candidate, not
broad API, cross-version semantic coverage, or fresh evidence for later
structured-query and closed-selector changes.

### Historical steering record: `tests/AGENTS.md` lines 585–735 at `cba4eefb`

Historical macOS evidence is split across three frozen 2026-07-31 roots. Initial
`a12` passed the four Alarm/Harbor version units and failed both Weather units;
fresh `a20-int22-weather` and `a24-int25-weather` roots passed the repaired
Weather units. This is passing evidence for all six unique units across roots,
not one single-candidate 6/6 campaign. Passing sandboxes were cleaned, failed
sandboxes remain quarantined, and every lifecycle record reports unchanged
source-project full hash and mtime. Those campaigns predate the structured
`query-schema`/`query-object --request-json` migration, the separately
disclosed bounded advanced-WAQL layer, and the removal of raw WAQL mutation
selectors. Those V1 roots do not validate the newer routing contracts; keep
the historical integration result attached only to its migration-before
candidate. The V2 evidence below applies only to its exact workflow paths.
The roots named in this paragraph and the 2026-08-03 macOS paragraph below
seal `runtime.platform=darwin`; later cross-host component reruns are recorded
separately.

The natural-language prompt revision received a fresh 2026-08-03 campaign.
`campaign-integration-workflows-v1-terra-20260803-current-r1` passed five of
six units. The 2025.1 Alarm failed safely on turn one because the Agent added a
redundant exact-ID Action lookup after the Event children row had already
returned `ActionType` and `Target`; no mutation occurred. After a query-reference
repair clarified that `Target.id` is the next Sound identity, fresh roots
`r2-int25-alarm-action-hop` and `r3-int22-alarm-action-hop` passed the 2025.1
and 2022.1 Alarm units on the same repaired candidate. Both repair roots pass
`--resume --verify-only`. Weather and Harbor loaded only the unchanged operate
reference and passed for both versions in `r1`. This gives all six current
prompt units passing evidence across roots, not a single repaired-candidate
6/6 run. All eight lifecycle records preserve source hashes and mtimes;
passing sandboxes were cleaned and the failed sandbox remains quarantined.
Those V1 roots do not validate the newer V2 fixture, routing, or workflow
contracts.

Later reruns used the legacy internal
`integration_workflows_cross_version_6` component, not the public composed
`integration` profile. At commit
`9e75a1aea496abcb9ef2a61e1da685adb99f4b01`, macOS root
`imac-wah-9e75a1a-r1` passed all six component units fresh and passed
`--resume --verify-only`. At commit
`9b4de8f618855091a424700b50ab8b0fd1989270`, macOS root
`imac-wah-9b4de8f-r1` passed five units and failed one, and native-Windows root
`iwin-wah-9b4de8f-r1` passed three and failed three; both failed roots were
frozen without verify-only replay. These runs are exact legacy-component
provenance, not current `integration` acceptance and not unified 12/12 evidence.

### Historical steering record: `tests/AGENTS.md` lines 748–767 at `cba4eefb`

The completed 2026-08-03 macOS evidence for that legacy component is
cumulative across frozen roots, not one final-candidate 6/6 run. `r8` passed
both Rifle units, `r12-2022` passed the
2022.1 Weapons unit, `r23-2022-footsteps` passed the 2022.1 Footsteps unit, and
`r24-2025-repairs` passed the 2025.1 Footsteps and Weapons units. All six unique
units therefore have passing evidence across those roots. Passing sandboxes
were removed; failed or blocked diagnostic sandboxes were sealed and
quarantined; every recorded source-project full hash and mtime remained
unchanged.

The later native-Windows evidence for that legacy component is also cumulative.
Commit `0dfea2b` root
`windows-v2-six-0dfea2b-r1` attempted all six units, passed 2022.1 Rifle,
2022.1 Footsteps, and 2025.1 Rifle, failed the other three, exited `1`, and had
no verify-only replay. At `a516835`, `a516-w22-r1` passed 2022.1 Weapons fresh
and verify-only; `a516-f25-r1` failed 2025.1 Footsteps and was frozen without
verify-only. At `f1b6a51`, `f1b-f25-r1` and `f1b-w25-r1` passed 2025.1
Footsteps and Weapons fresh and verify-only. All six V2 units therefore have
native-Windows passing evidence across these frozen roots, but there is no
single-root or single-candidate Windows 6/6 result.
