# Native observations needed by current implementation

Parent: [#174](https://github.com/zcyh147/waapi-skill/issues/174).
These observations unblock implementation decisions. Each row stays open until
the implementation and its required verification are complete. The full scope
and existing obligations remain in SPEC.md and LEDGER.md.

## Inline WAV without Base64 padding — #182 / #180

The pinned 2023.1–2025.1 definition
`waapi_definitions.json#/definitions/oneImportFile/properties/audioFileBase64`
requires a trailing padded Base64 group. A valid WAV whose byte length is
divisible by three has canonical Base64 without `=`. Complete compiled-request
validation therefore rejects some valid WAV encodings before dispatch.

Two preserved counterexamples are a complete 44-byte PCM WAV with padding and
a complete 48-byte PCM WAV with two frames and no padding. Their bytes and the
three exact source patterns are in
`/tmp/full-coverage-shared-inline-schema-obligation.json`. The current
`object.set` rejection is diagnostic, but inline-media compatibility is still
unfinished. Changing old source-control fixtures to the padded WAV only
isolates those fixtures' intended behavior.

The committed reproduction is
`tests/unit/test_object_native_surface.py::test_object_set_2023_inline_wav_import_is_canonicalized`:
mono 16-bit PCM at 44100 Hz, zero frames versus two zero-valued frames. The
48-byte file SHA-256 is
`0588c6a627c6603830a9e5d87ab258d4977c02876b9bac8f9598fccef098c1cf`.

Obtain exact matching native evidence for the unpadded case and a padded control,
including the resulting source/media bytes. Historical searches of named
`object_set.json` receipts in the ignored campaign and evidence trees found no
matching `audioFileBase64` receipt. Do not add padding, modify the audio, silently
skip the constraint, or call this a native absence. Any schema compatibility
treatment needs the exact native result and version scope first.

## Generic inline Curve field eligibility — #180 / #178

The 2022.1–2025.1 `curveObjectDefinition` proves the object.set value shape.
The historical C06 receipt proves a real RTPC `@Curve` readback containing an
identity and points. Neither establishes which getPropertyInfo metadata admits
that field. Current generic construction requires explicit live metadata that
allows a Curve; synthetic field fixtures grant conditional program evidence.

For a real RTPC, retain getTypes identities for RTPC and Curve, the exact
property/reference name list, class- and object-scoped Curve metadata, and the
referenced Curve identity/type/points. Check every supported version; generic
object.set itself starts in 2022.1. A targeted search of historical
getPropertyInfo receipts found no exact `property=Curve` response. No Curve type
alias or universal reference-field applicability may be invented from that
search result. Keep multi-reference field cardinality as a separate open
applicability question.

## Console artifact representations — #184

`moveMediaIdsToSingleFile` names the central media-ID artifact but does not
establish its container or mapping semantics. The current observer preserves
bounded bytes and reports the representation as unestablished. Retain a source
Work Unit, central file, and corresponding post-operation Work Unit before
cleanup, then implement and verify the complete mapping oracle.

`dumpObjects` produces JSON, but the content/session alternatives need native
representation evidence before a syntactically valid file can prove the
requested dump. The existing native dump case now retains its original bytes
and selected options. Follow up on the remaining content/session alternatives.

Prepared cases use the existing workflow sandbox and category finalizer:

- `test_cli_console_media_id_file_observation`
- `test_cli_console_business_object_dump`

Run terminal CLI nodes individually in their own sequential lifecycles after
the implementation hold is lifted. Retain original failures and source/host/
candidate provenance. Format capture alone grants no business-effect coverage.

## October 18 targeted native results and remaining work

These observations supersede the pending-evidence statements above only for the
exact tested branches. Original failures and quarantines remain unchanged.
No complete ticket, full native matrix or Fresh acceptance is claimed.

Current product candidate `c98897e2625df00606192f557f452f9a5fd26cc7` contains
R14's exact-definition inline WAV compatibility and language-specific import
verification fixes. On macOS Console 2023.1.19.8928, 2024.1.13.9056 and
2025.1.7.9143, the canonical 48-byte unpadded WAV passed full public transaction
verification and independent Sound → AudioFileSource → Originals file/PCM
checks. All three file hashes equal the SHA-256 above. This is SFX evidence;
localized replacement, uppercase `.WAV` path compatibility, other import
branches and complete #182 acceptance remain open. Earlier historical candidate
receipts accepted media but failed Gateway verification; they are not regraded.

The same candidate exposed a Short ID lookup gap under #181. Typed Event lookup
and exact-ID readback succeeded on all five versions. DialogueEvent
`Objective_Status`, Short ID `3970659059`, was discovered normally but missed by
typed Short ID lookup on 2021.1, 2022.1 and 2023.1; the identical ID lookup
succeeded on 2024.1 and 2025.1. Subsequent read-only diagnosis at `f7c77edc` found
that equivalent decimal comparisons succeed on the older three versions while
integer and signed-conversion comparisons fail. Repair `b347acfa` changes only
the older typed-query literal rendering; the public uint32 identity and exact
GUID/type checks stay unchanged. The original Event/DialogueEvent observation
node passed on each affected version, with unchanged source hashes/mtimes,
removed PASS sandboxes and no owned process residue. The three original c988
failures remain failures. This does not establish an internal overflow cause,
Definition mutation acceptance, collision handling or complete #181 coverage.

Real RTPC.Curve class/object metadata and referenced Curve observations now
exist for 2022.1–2025.1. The 2021.1 collector retained absent type-discovery
matches and unavailable public curve-points projection as gaps, not engine
absence. The 2022.1 observation passed at c988; 2023.1–2025.1 observations remain
on their original historical diagnostic candidates and were not repeated.

Owned-list observations remain incomplete on all five versions. Fresh names
did not disclose sampled RTPC/Effects/Arguments lists even where bounded native
relationship reads returned members. Native rows omitted `owner` on ordinary
objects and `parent` on owned objects; missing is not silently null. In 2025.1
the MusicSwitchContainer Arguments member returned type `PluginInnerObject`,
while its path identified a MusicArgumentsSlot. A later exact observation on
`5d7213cb` returned `class_id:5832704`, matching the retained MusicArgumentsSlot
class declaration without rewriting native type. The member's owner matched the
container and its parent was omitted, not null; exact-ID readback reproduced
these facts. This resolves that sampled member's class identity only. The old
type guard prevented the inner Argument hop, so that hop was not observed.
Universal discovery, cardinality, owned-graph completeness and write effects
remain unfinished under #180/#181; the observer's SKIP is not coverage.

Durable ignored receipts: `.waapi-skill-state/full-coverage/native-c98897e2-r1/summary.json`
contains all five candidate/build/response and final lifecycle references.
`native-23ae9be2-r1/triage.json` retains the original 2021 test-script failure
(`--kind event`, rejected before lookup) and its two completed read observations.
The successor repaired only that syntax and proved the whole collector through
the actual Gateway with fake native dispatch. Only the failed Short ID case was
repeated on 2021. Every final record proves unchanged source hashes/mtime and
no scoped process residue. Mixed failed/SKIP lifecycles stay quarantined,
including those with an individual WAV PASS; no whole lifecycle passed.

## Prospective group/default creation — #178

Fixed `5d7213cbdd114dd7e9ab976f6493a272c91becd9` passed the Switch and
State same-create cases on each matching 2021.1–2025.1 Console version:
**10 individual native PASSs**. The public Gateway created each SwitchContainer
once with explicit existing group/default choices; independent exact-GUID reads
proved root identity, parent and both references, with selected group/child
identities preserved. No later setReference repair or creation retry was used.
Other new-object conditions and placements remain open.

The 2021–2024 lifecycles passed with sandbox deletion. The 2025 invocation also
selected the owned-list observer: **2 passed / 1 skipped**, whole lifecycle SKIP,
sandbox quarantined. Its class observation above is useful evidence, not complete
list discovery or a three-node PASS. Every version preserved source hashes,
mtime/tree metadata and tracked files, and had no owned process residue.
Original results, final lifecycle records and observations remain in the query
worktree's ignored `native-5d7213cb-r1/summary.json`; summary/handoff and small
terminal receipts are also archived under `integration-partials-r18`. No native
ledger state, Windows/Fresh acceptance or ticket closure follows from this run.


## Exact 2021 RTPC identity observation — #180

The read-only `8e9b9f17` observation on 2021.1.14.8108 resolves saved RTPC
`{A809A571-6012-42BE-A00D-D8E7C89D1248}` as type RTPC, class 1441808, empty
name and an opaque Voice Pitch/RPM display path. Its owner is the independently
read Sound `{9EEFCC8E-7FC2-4CDC-8BE9-C682F2CA77CC}`. Complete names inventories
contain 111 Sound fields and only Color, ControlInput, OverrideColor for RTPC.
ControlInput detail has an empty type and empty restriction; Curve and
PropertyName were not disclosed. Missing parent on RTPC and missing owner on
Sound remain omissions, not null values.

Ten public calls completed with source hash/mtime/tree unchanged and owned
cleanup. Original report and hash summary live in the authoring worktree's
`.waapi-skill-state/full-coverage/rtpc-2021-representation-8e9b9f17-r1/`. The
collection test passes only its diagnostic protocol; its business category is
blocked. This settles existing identity/class/owner observation, not creation,
ControlInput mutation applicability, owner-list token, arbitrary Curve-point
construction, or native absence. No further launch is needed to rediscover
these same facts.

## Existing anonymous EffectSlot exact-member effects — #180

Frozen `4fac9727` passed the existing exact-ID collector once on each macOS
Console lane 2023.1, 2024.1 and 2025.1. Each lifecycle verifies two separately
previewed effects: selected Bypass=true, then owner rename plus Bypass=false.
Independent public reads check ordered membership, both slots and local Effects,
class/owner/reference/scalar values, notes, paths and parent availability.
Three setup transactions are excluded from effect coverage. Source full hashes,
mtime/tree and all tracked files stayed unchanged; PASS sandboxes were deleted
and no owned process remained. The three original roots and summary are
`.waapi-skill-state/full-coverage/effect-slot-exact-4fac9727-{2023,2024,2025}-r1`
and `effect-slot-exact-4fac9727-native-summary.json` in the root checkout.

The earlier `f4c245b6` 2025 attempt remains FAIL/quarantined. Its collector had
invented a local Effect hierarchy parent and direct Sound owner; the actual
representation is immediate slot owner with parent unavailable. The corrected
collector retains, rather than normalizes away, that observed absence.

This closes these exact candidate/version native witnesses only. New anonymous
List construction, empty-name conflict semantics, planned plugin targets and
RTPC graph/Exclusive native effects still require implementation or evidence.
Legacy 2021/2022 scalar EffectN contracts are distinct. No blanket owner rule,
inline List merge, Windows, Fresh or whole-ticket completion follows.

## R29 actual RTPC graph and Authoring outcomes

Root `.waapi-skill-state/full-coverage/rtpc-graph-96660a68-2025-r1` is an
overall FAIL with four verified effect phases, followed by an accepted replaceAll
whose sole failing Gateway assertion compares RTPC membership order. The raw
native owner accessor and returned associations both retain Volume then
CenterPercentage. Gateway incorrectly compares a GUID-sorted normalized snapshot
instead. Pair identities, curves and the other assertions passed. Repair the
ordered verifier to use its already-validated original member sequence;
retain ordered Effects checks and every GUID/cardinality/ownership/preservation
check. Do not replay the original transaction or call this complete acceptance.
The original final category records source full-hash/mtime/tree preservation,
clean process shutdown and a quarantined failed sandbox.

Earlier 2025 roots at `66413dbd` and `28dc59aa` remain failures. The former
exposed missing prospective-source inputs to sharedOnlyTypes validation; the
latter passed initial curve creation but its collector incorrectly required the
base property to remain enabled after Exclusive RTPC attachment. Their fixes
have public regressions and progressed the later native case; original results
are never rewritten. New anonymous Effects construction still needs its own
native collector and carries no credit from exact-member tests.

Authoring 2024 roots at `8db47c61`, `bd6d9521`, `8d20e25a`, `02a42a09` and
`7459b8ea` preserve distinct startup failures. The last restores the historically
proved direct-Wine command and retains a partial, ownership-certified process
sample. It does not prove a particular modal, a disabled WAAPI preference or
successful initialization. Current computer-control inventory cannot identify
this direct-Wine window by its host PID. Continue diagnosis from retained evidence
or an explicitly supported window-observation route; do not copy global user
preferences, accept an unobserved license prompt, or repeat blind timeouts.

## R30 RTPC acceptance and Effect Render follow-up

The ordered-membership correction uses the validated native member sequence;
GUID-normalized snapshots still serve identity-set and preservation checks.
On fixed `e2bbf7e5`, the existing RTPC graph case passed once on each macOS
Console 2023.1, 2024.1 and 2025.1 (25.26s, 22.73s and 23.66s).
Each case verified all five separate effect phases and the Exclusive conflict
negative. The 2022.1 attempt on that candidate failed before the first intended
effect: an owner-null predicate incorrectly rejected an independent GameParameter.

Fixed `567a9fd3` changes only the 2022 shared-target strategy to a documented,
bounded exact-source/owner projection. Canonical parent validation remains;
missing, malformed, duplicate and extra results cannot establish a shared target.
The same 2022 RTPC case then passed (24.29s), including all five effect phases.
The 2023–2025 classifier is unchanged. These are version-specific component
results on two fixed candidates, not one final release gate. All passing
lifecycles preserved source full hashes, mtimes/tree metadata and 1,881 tracked
files, deleted their sandboxes and left no owned process. Original failures
remain quarantined. Evidence lives under `rtpc-graph-e2bbf7e5-*-r1` in the query
worktree and `rtpc-graph-567a9fd3-2022-r1` in the short-ID worktree.

The separate 2025 anonymous EffectSlot constructor on `e2bbf7e5` failed
(8.05s): Wwise accepted the write, then changed an earlier Render=false to true
when a later effect requested Render=true. Matching help for all five versions
documents this automatic prefix behavior. This is a Gateway condition-planning
gap, not an identity/order failure. The repair must reject contradictory explicit
values and disclose and verify induced predecessor changes across applicable
routes. The original failed sandbox is retained. No constructor PASS, rendered
audio claim or whole-ticket completion follows from the RTPC results.
