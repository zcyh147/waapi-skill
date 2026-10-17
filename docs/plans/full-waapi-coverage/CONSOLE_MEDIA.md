# Console media-ID native facts and pending verification

Parent: #174; implementation owner: #184. Exact facts below came from the existing
isolated workflow lifecycle, not direct-client scripts. All original native runs
remain FAIL; format observations and a process result do not establish the requested
business effect or preservation. No failed transaction was replayed.

| Wwise Console build | Candidate | Native result | Central mapping rows |
| --- | --- | --- | --- |
| 2021.1.14.8108 | `c6739d03` | `{"result": 2}` | 1066 |
| 2022.1.19.8584 | `c6739d03` | `{"result": 0}` | 748 |
| 2023.1.19.8928 | `c6739d03` | `{"result": 2}` | 734 |
| 2024.1.13.9056 | `c6739d03` | `{"result": 2}` | 734 |
| 2025.1.7.9143 | `5d7213cb` | `{"result": 2}` | 749 |

The 2021–2023 `moveMediaIdsToSingleFile` result schema is an empty object with
`additionalProperties:false`, SHA-256
`99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa`.
Matching native calls returned a process result anyway. The exact URI/version/source
compatibility rule accepts only `{result: 0|1|2}` or the original empty shape, reports
its rule/build provenance, and retains independent artifact verification. It does
not generalize to other commands or alter reflected resources. The existing
`processResultCli` outcome meanings remain success/errors/warnings; errors retain
possible partial effects and no automatic retry.

All five central files are UTF-8 XML rooted at `WwiseDocument Type="MediaIDs"`,
with `MediaIDInfo/MediaIDs/Language/File/WObject/MediaID` entries and optional
per-platform `Hash` children. Language IDs may omit Name; actual plugin-media
sources are present, alongside audio and MIDI sources. Exact mapping semantics
and write-back/update alternatives still require implementation and verification.
Do not treat the central XML being present as complete business acceptance.

The original 2021 attempt on `5d7213cb` stopped before writing because verbose
identity lists exceeded the 512 KiB snapshot limit. Repair `c6739d03` hashes each
complete sorted per-file identity/media multiset and retains counts; file/XML
collection, byte limits and race/preservation checks remain. The successor reached
execution and produced the central file, then exposed the process-result mismatch.
The 2024/2025 preservation checks found saved XML changes outside media storage.
Compare those changes with the actual immutable Preview, after sandbox setup:
the fixture already isolates optional plugins in 2022 and Auro in 2025. An
original-source-versus-final-file comparison cannot distinguish that setup from
native command effects. In particular, the 2022 prepared snapshot contains 748
media rows, matching the 748 central rows; the source project's extra plugin row
was removed by setup, not lost by this command. Prepared counts match central
counts on all five versions. Non-media XML differences against the actual Preview
remain separately recorded and require interpretation; do not weaken preservation
or infer a business PASS merely from matching counts.

Durable local receipt index: query worktree
`.waapi-skill-state/full-coverage/console-format-native-summary.json`.
The corrected prepared-baseline comparison is
`console-media-actual-preview-comparison.json` in that same directory.
Original run/category/dispatcher records are under
`console-format-native-5d7213cb-r1` and `console-format-native-c6739d03-r1`.
All source-project hashes/mtimes and tracked candidates remained unchanged;
owned processes ended and failed sandboxes remain quarantined.

Exact dispatcher receipt SHA-256 (original bytes retained):

- 2021.1: `1ecdc35b7fc25569d30245d476b79882e1606c338942445415f4f971bac4e818`
- 2022.1: `2f3c9bbde9c85f6b252df88ece2ad63023d2c09de2d030b4aba42d7adc3dc09a`
- 2023.1: `d037bc78189e6b5178e1db4b060c1b8d7462360168cf1ee28df81de70aaaf96c`
- 2024.1: `e55eb3635936b8aeeb0f1a89b6b2d39c881e31f0c2881911bb25ffc7af29dd0a`
- 2025.1: `09d7ab7073c116420db6ccbc72d2f4040b89139efc409fe7021c318a5dc5374b`

## Source-backed mapping verifier checkpoint

The move-to-single-file verifier now compares complete compact records for each
source GUID, language ID/name, actual filename and every MediaID attribute. It
also requires empty Work Unit media lists, the exact project storage-mode setting,
matching source descriptors and preservation outside those storage fields. An
already-central input uses its sealed pre-existing mapping. Same-named properties
on other objects are not elided by the preservation projection. Audio, MIDI and
plugin-media descriptors use their separate saved fields; generated platform hashes
are bounded observations, not conversion-correctness proof.

Language ID construction follows `AK::FNVHash32::ComputeLowerCase` in matching
2021–2025 installed SDK `include/AK/Tools/Common/AkFNVHash.h`: FNV-1 over UTF-8
bytes with ASCII A–Z folding. That function region has the same normalized-text
SHA-256 in all five SDKs:
`6da4651c79424adb232096aae184b8847e1ac2f7835b10fcb52848fbd089a56c`.
The literal SFX/English native records provide independent known results.

Public controls cover all five versions, audio/MIDI/plugin sources, already-central
storage, changed owner/media/language/file, duplicates, missing rows, unchanged
mode, remaining Work Unit IDs and unrelated property changes. The final affected
selection passed 24 tests in 11.80 seconds. Earlier REDs and focused results remain
separate. This is program evidence; current native acceptance, transfer back to
Work Units, refresh semantics and other storage variants remain same-parent work.

## Saved-baseline native check and representation repair

Exact `3d05ddd1` ran the existing isolated 2025.1 lifecycle after a separate public
Gateway project save. It failed (1 failed, 11.79 seconds), with all 749 full mapping
records matching, no remaining Work Unit media IDs and the correct storage mode.
Non-storage preservation alone failed; the source and candidate were unchanged,
owned processes ended and the sandbox remains quarantined. This is not a PASS.

Its immutable Preview file hashes establish two serialization differences:

- `Effects/Factory McDSP Effects.wwu` matches the original fixture byte-for-byte
  before dispatch. All 1569 scalar Property values survive unchanged, expressed
  as one unqualified `ValueList/Value` instead of a `Value` attribute.
- `Busses/Default Work Unit.wwu` baseline was reconstructed by the existing
  read-only Auro prelaunch preparation and matched the exact Preview SHA-256
  `dbd6e902dd8f062900f3c7e6ed38c55998d1af194e7d77d5d56c3e11f455992a`.
  The sole change is removal of an empty, unattributed EffectSlot ReferenceList.

The model comparison now normalizes precisely these equivalent forms. It retains
name, type and literal value; platform-specific, dual-encoded, nested or attributed
values and nonempty/attributed references remain distinguishable. Public Gateway
controls cover all five versions and reject actual value/platform/reference
changes: original RED 1 failed, successor 1 passed, then 31 affected cases passed
in 15.22 seconds. This program evidence does not regrade the native failure.

Native failure also exposed a misleading summary: a failed artifact check was
called a reported Console error, and strong success was described as unverified.
The summary now distinguishes verified effects, unresolved effects, actual native
errors and failed verification. Its public RED retained 2 failed / 2 passed;
message controls and migration regression passed 14 cases in 7.00 seconds.
