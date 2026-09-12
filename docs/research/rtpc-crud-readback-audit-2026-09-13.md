# RTPC preview and related CRUD readbacks — 2026-09-13

## Scope and candidates

Baseline: `0db5ceb`. Runtime acceptance candidate:
`a18110c8d457ffc1b843110c3cbd6bf3633fd750`.
Branch: `codex/fix-rtpc-empty-readback`.

The triggering demonstration is task
`01a096f8-09d8-74f3-aad6-ad986d9acdda`, using macOS Wwise Authoring
2024.1.13.9056. Sol / High and memory isolation are operator-reported context,
not new Agent evidence from this repair. The user expanded the investigation
to related CRUD behavior and authorized isolated WwiseConsole experiments.
No Fresh Agent or full integration campaign was run.

## Root cause and related findings

| Finding | Evidence | Repair |
| --- | --- | --- |
| Empty RTPC owner accessor rejected on 2024.1 | `draft-check` reached `prepare_operation` -> `_prepare_object_set_rtpc` -> `_read_rtpc_rows_with_evidence`. The exact owner query requested `id,@RTPC`; Wwise returned only the correct id. Independent bounded WAQL list selection returned zero members. | Replace the 2022/2025 omission whitelist with a bounded, fixed-list emptiness proof. A missing field is not itself proof of emptiness. |
| Effects had the same unsupported empty-list inference | The adjacent Effects reader accepted an id-only owner row without independent confirmation. | Reuse the same proof for the fixed Effects list, retaining the selected platform. Arbitrary/custom-list omissions remain strict. |
| Effect ownership was mistaken for hierarchy parenting | Real 2024 EffectSlot returned `owner=Sound`, no `parent`; its Effect returned `owner=EffectSlot`, no `parent`. The previous verifier rejected the missing parent. | Validate the complete owner chain and slot's `@Effect` binding. Explicit contradictory parents/owners still fail. Raw readbacks remain evidence; owner-only placement is labeled. |
| 2022 empty fixed Effect slots looked like duplicate plugins | Real 2022 returned four null GUID references, not four Python `None` values. | Normalize the null GUID only in nullable reference positions. Preserve occupied slots and validate new plugin placement. |
| RTPC GUIDs incorrectly qualified for ordinary deletion | Real 2024 rejected direct `ak.wwise.core.object.delete` on an RTPC after preview had succeeded. | Reject RTPC deletion before immutable preview with `EMBEDDED_OBJECT_DELETE_BOUNDARY`. Do not delete the owner or replay the rejected transaction as a workaround. |
| Reference clearing used the wrong wire value | Real 2024 rejected JSON `null` against the reflected `objectArg` schema. | Keep business `target=None`; compile the native setter value to the all-zero GUID. |
| Missing/wrong reference readback could be accepted as cleared | Five-version program negatives reproduced success from a missing field or wrong source GUID. Malformed null-reference objects were also checked. | Require the exact source and requested projection for field preparation, drift guards and verification. Explicit null values remain distinct from missing data. |
| Failed verification still advertised `business_state_verified=true` | The failed Effect verifier had contradictory status/flag fields. | Non-verified results cannot claim business-state verification. Verification strength remains a separate field. |

The original failure was not a Draft revision problem. Its public revision was
5; no immutable RTPC preview or mutation was produced by that failed call.

## Why earlier tests missed it

The old RTPC compatibility set explicitly contained only 2022.1 and 2025.1;
an existing negative test deliberately rejected id-only owners in 2023.1 and
2024.1. The public Gateway RTPC test stopped after declaration materialization,
before `draft-check`. Some real metadata/graph workflows were explicitly limited
to 2022.1 and 2025.1. Fake Effect rows also supplied hierarchy parents that were
absent in real embedded-object readbacks.

This explains these gaps, not a claim that every intermediate-version API was
broken. The five-version packaged route partition and version boundaries were
retained. In particular, 2021 has no packaged `object.set`-based RTPC creation
route; rejecting `object.setRTPC` there is intentional, not a missing empty-list
compatibility entry.

## Verification

Focused program selection: **623 passed** before the inventory-only golden
update. It includes public Gateway declaration -> check -> immutable preview
on 2022/2023/2024/2025, operation preparation/guards/verification, explicit empty
and populated lists, malformed proofs, wrong identities, nullable GUIDs,
reference clearing and the direct RTPC deletion boundary.

The five real invocations below used the **same frozen runtime and test
candidate `a18110c`**, matching Console executables and disposable copies of
each version's SampleProject. They ran sequentially on macOS, on independent
ports, without replacing or closing the operator's Authoring process.

| Wwise | Result | Meaning |
| --- | --- | --- |
| 2021.1.14.8108 | 3 passed / 24 deselected | Ordinary CRUD, property/reference assignment and initially-null Attenuation clearing; explicit unsupported RTPC boundary, **not** RTPC/Effect creation credit. |
| 2022.1.19.8584 | 3 passed / 24 deselected | Same ordinary CRUD and fields; RTPC first creation/update, direct-delete rejection, disposable-owner deletion/recreation; two fixed-slot Effects. |
| 2023.1.19.8928 | 3 passed / 24 deselected | Same list lifecycle using EffectSlots; property/reference changes, null reference and platform unlink. |
| 2024.1.13.9056 | 3 passed / 24 deselected | Same scope, including the original empty-RTPC condition. |
| 2025.1.7.9143 | 3 passed / 24 deselected | Same scope with the Containers hierarchy. |

The ordinary lifecycle node creates source/destination fixtures, renames,
changes notes, copies, moves and deletes them through closed Gateway Drafts,
immutable previews, confirmations, single executions and verification. The
list node checks three-point curves, in-place RTPC identity preservation,
explicit rejection of direct RTPC deletion and fresh creation on a recreated
disposable owner. Owner recreation is fixture lifecycle, **not** an RTPC-removal
workaround offered to users. Effect append verification preserves existing
slots. These are real Wwise **program-driven** checks, not 15 Fresh tasks or
exhaustive coverage of every URI/object type/parameter combination.

All five final category records report unchanged source hashes, tree metadata
and project mtimes, deleted passing sandboxes and zero scoped residual
processes. Earlier failed experiment records remain failed; they are not
reclassified by later passes.

Run selection (the destructive mode already owns its test paths):

```sh
ci/test.sh --version 2024.1 --mode destructive -- -q -ra \
  -k 'rtpc_empty_create_update_delete_recreate or object_lifecycle_business_draft_executes_all_five or object_metadata_business_draft_executes_field'
```

Final Program and Non-live gate totals are recorded below after completion.

## Actual demonstration preservation

The failed Draft `od1-35434475d991d3c939fb41419e2c31f0` was copied before
repair. Its SHA-256 is
`24a0f945cb4f8d5610ef6a26637abf34c91b9f69ff0ccc388cb18247ee61be17`.
The original task trace and copied Draft are retained under ignored
`skills/waapi-skill-workspace/rtpc-readback-20260913/`.

On the actual Authoring 2024.1 Rain_Bed, a **new isolated Draft** passed
`draft-check` and produced immutable preview `tx1-34xkxgady5qpvyr0tbxs` for
Volume -> Rain_Intensity with `(0,-48), (50,-12), (100,0)`, Linear. No `execute`
was issued. The global `allow_changes` policy made that diagnostic preview
`policy_authorized`; `reject` correctly refused because it only handles
`awaiting_confirmation`. The isolated preview is left to expire, never replayed.
It is not in the demonstration task's normal state directory.

No weather import, Action edit, old Draft/transaction replay or project reset
was performed. The RTPC remains uncreated in the user's demonstration; Console
mutation success must not be described as completing that demonstration.

Durable evidence includes the final category ledger snapshot and detailed final
2023/2024/2025 Console state/dispatcher artifacts. The 2021/2022 final outcomes
and source-integrity proofs remain in the category ledger and terminal record;
their default pytest temporary directories were already rotated. Original
failure evidence is preserved separately and does not depend on pytest's
temporary-directory retention.
