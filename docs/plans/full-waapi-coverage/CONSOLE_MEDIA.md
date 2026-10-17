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
The 2024/2025 preservation checks also found unrelated saved-model changes:
Auro references/effects were removed and McDSP properties changed representation.
Keep those checks; future native acceptance needs suitable isolated fixtures.

Durable local receipt index: query worktree
`.waapi-skill-state/full-coverage/console-format-native-summary.json`.
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
