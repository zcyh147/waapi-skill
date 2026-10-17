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
