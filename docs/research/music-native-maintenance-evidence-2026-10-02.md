# Native music investigation evidence, 2026-10-02

Candidate: `78c3587e15951e784e86791714bcd13d016716c2` (#129 repair). This is derived evidence from completed owned-copy WwiseConsole runs on macOS: 2022.1.19 build 8584 and 2025.1.7 build 9143. It supplies no Fresh Agent, native-Windows, playback, or complete M03/M04/M06 acceptance credit. No test or host was launched while preparing this summary.

Evidence root: `/Users/xiye/.codex/worktrees/music-capability-probes/waapi-skills/.waapi-skill-state/evidence/waapi-test-remediation/music-native-78c3587-r1/`. The ignored originals remain the authority; hashes below identify their exact bytes.

## Completed runs and bounded outcomes

| Lane | Pytest result | JUnit result |
| --- | --- | --- |
| 2022.1 | 4 passed, 32 deselected, 14.82 seconds | 4 tests; 0 failures/errors/skips; 14.808 seconds |
| 2025.1 | 5 passed, 32 deselected, 25.61 seconds | 5 tests; 0 failures/errors/skips; 25.599 seconds |

The separate 2025 smoke reached readiness in 5.68374270782806 seconds and recorded cleaned shutdown and sandbox deletion. Each native node has its own final v3 record; all nine selected node outcomes are PASS. Supplementary `authoring-ui` categories remain `blocked/host_unavailable` on Console.

| Investigation | Exact established outcome | Remaining boundary |
| --- | --- | --- |
| Playlist reads | 2022 retained 7 returned reads, 1 clarification, 3 rejected reads; 2025 returned all 11 planned reads. No transactions. | Read-investigation PASS means bounded findings were retained, not complete ordered configuration or loop maintenance. |
| Transition reads | Both lanes returned all 41 planned reads. `time` and `offset` property-state reads on existing MusicFade `{0FC1E836-74BB-43AB-B417-6C9D16AE5636}` returned enabled on project platform Mac. | Field availability does not establish native physical units, conversion, dependent fade changes, or complete M04. |
| Populated Transition scalar | Both lanes changed live-attested `PlaySourcePostExit` false→true on `{E49EF1AA-29FB-40F1-B343-523AF28244AE}` under `{8A6F5BFD-8784-474D-8BDE-6460595AA1FC}`. Exact approved scalar Preview/confirm/execute/strong verify plus a separate closed save: two transactions per lane. Independent saved XML retained all 15 rules in order, 14 sibling subtrees, other references/fades/music graph, and original media. | Save's Gateway terminal state is `result_schema_checked`; saved XML supplies the independent readback. `complete_M04_verified=false`; context/timing/fade edits were not requested or performed. |
| Music Switch reads | 2022 retained 5 returned reads and native unknown-property rejections for `@Arguments` and `@Entries`; 2025 returned all 45 planned reads. No transactions. | The 2022 rejection bounds those accessors, not all possible earlier-version representations. Returned row order is not order authority. |
| Existing Music Switch reference | 2025 entry `{903A30EC-F1F4-49FF-9CBC-99B89539598B}` retargeted AudioNode from Stealth `{20FA9A69-7ECC-4B05-BD6B-2C9527CD88C2}` to Fight `{1D0ECA1F-2749-4DBB-B92C-0DBDFDA7A825}` in one approved/confirmed/executed/verified transaction. All 12 independent assertions passed, preserving the other eight entries, two arguments, eighteen condition references, owner, music contents and media. | Selected-reference maintenance only: saved WWU stayed unchanged, authoritative condition/path order remains unproven, `complete_workflow_verified=false`, and no 2022 mutation credit. |

Earlier ambiguity, failed mutations, and the b23011f Transition call-PASS/teardown-error root retain their original classifications. These new final records neither repair old evidence nor add Gateway capabilities.

## Source and cleanup guards

All nine raw final-record digests were recomputed and matched `verified-native-records.json`; candidate, selected node, final phase and PASS outcome also matched. Every record has equal before/after full regular-file content hash, project mtime, tree metadata, file count and bytes hashed, and records a deleted owned sandbox with cleaned scoped processes and an empty residual list.

| Source lane | Full content SHA-256 | Project mtime, ns | Tree-metadata SHA-256 | Files / bytes hashed |
| --- | --- | --- | --- | --- |
| 2022.1 | `0094292bd34fd6581cff062ce8aa6f715aba82556d7f783847e478c89913836e` | `1790531309484673590` | `d776f776633e0c49602eb6300ad608e07e54c83141840c9dcf06a7cb54004d4c` | 84 / 3,788,783 |
| 2025.1 | `60855d800d1e95c7b8684d8c35f2fda247bc3c4d716f1375b6cded212c8c72bd` | `1790531309503233691` | `b3631e0fb271401f09b7767e67d07e988b0c5c9a4c186466114f9c2f765eb9d7` | 83 / 3,943,065 |

## Exact artifact digests

| Artifact under the evidence root | SHA-256 |
| --- | --- |
| `2022-run.log` | `6f796832be521a3939c4b87b9b91a852c391e5e2baa88533f826000f04463828` |
| `2022-junit.xml` | `aa1f676a69bc80f53cd634f4ee2f883b4502de83ce92449966810d1a9a5b7c62` |
| `2025-run.log` | `fdf8ab0ad96aeddc88afbab4c24a4d6ed01ef35199df2087043853b9ec69e0aa` |
| `2025-junit.xml` | `3b4f20a7964876c0ecf9b759f62cbc299930b741634271146faee1c190340515` |
| `2025-smoke.log` | `e53cfec64dee3e940a5ea26d6e31592b0ae32481bbcbffbe71957a5a9426eeb8` |
| `verified-native-records.json` | `c1609883ca567facaede4aa6dcc49d5087dab7f9d5687b60f233d4092f7980e7` |

| Final record | Selected native node | SHA-256 |
| --- | --- | --- |
| `final-record-1.json` | 2022 Playlist reads | `abe2c31e5d836ecb2282195ad4135598724c794fc6dfcbd15f76f105bd8bc5ac` |
| `final-record-2.json` | 2022 Transition reads | `43e56e3cf683aaebc3be477f1fe93e6820f98051751a0e3f97bb41deed26b618` |
| `final-record-3.json` | 2022 Music Switch reads | `426bfdcca02eb927206f2ce9524be8a37addab09bbc61c82fcd6ba8cac9c529d` |
| `final-record-4.json` | 2022 populated Transition scalar | `6169e30aaaeaff2db0f4f09b775fafd8c554a159208e6aa6ebdad78a5cc2c646` |
| `final-record-5.json` | 2025 Playlist reads | `4fc295e118a92b1a3264a95848f53e12424b6014547a849589f31a88c731e476` |
| `final-record-6.json` | 2025 Transition reads | `33fe6e59fbc404f170c2d410b33b94dc49c302cfe44dad38264b5a5f6145c6a8` |
| `final-record-7.json` | 2025 Music Switch reads | `496da0359a9ac3f566af6ac7695c4343da04de316dbc7ed34d0652a0e6254d5f` |
| `final-record-8.json` | 2025 populated Transition scalar | `bd119b23b679b2dd46600da62a8b1babf56cf1c97c33a8f042e590be57bd0dd8` |
| `final-record-9.json` | 2025 selected AudioNode reference | `447594a74fdc5c0437983b0b983c8aedaf66b5e627fcdbcae7cacc7ad50d45c2` |
