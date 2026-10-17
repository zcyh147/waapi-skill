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
