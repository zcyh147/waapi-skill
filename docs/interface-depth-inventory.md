# Interface-depth inventory

This report is generated from the exact five-version public surface and the reviewed policy in `interface-depth-review-policy.json`. The 824-lane construction baseline proves typed request construction only; it is not evidence that every interface is deep. Every permitted public API and supported version lane must converge on the same Gateway-owned business/domain boundary; simplicity and prior test PASS are not migration exemptions.

## Exact coverage

- Native function/Topic lanes: **824**
- Named-operation lanes: **153**
- Migration families: **15**
- Unowned migration rows: **0**

Every exact row, version, schema digest, continuation command, field ownership, disposition, and owner is recorded in `interface-depth-inventory.json`.

## Ownership boundary

| Class | Meaning |
| --- | --- |
| `bounded_domain_expression` | An exact domain expression is accepted only by its reviewed read-only or code boundary. |
| `exact_user_artifact` | User-owned bytes, files, paths, tables, or source text remain exact inputs inside a Gateway envelope. |
| `gateway_derivation` | The Gateway deterministically derives or serializes this value or workflow mechanic. |
| `live_bound_handle` | The Gateway issues a capability- and live-state-bound handle which the caller may only copy. |
| `prohibited_boundary` | The value or route is intentionally unavailable through the public surface. |
| `reviewed_adapter` | An operation-specific Adapter must replace the current native-facing value or structure. |
| `stable_business_declaration` | A prompt-derived business value remains visible in the public request. |

Business scalar values remain visible. Native paths, metadata scope, property/reference tokens, dependency order, batch layout, revision arithmetic, request fragments, continuation selection, wire types, and shell quoting are Gateway-owned.

## Migration ticket families

| Family | Roll-up | Exact rows | Versions | Unique API/operation names | Row digest |
| --- | ---: | ---: | --- | ---: | --- |
| [`generic-cli-console`](https://github.com/zcyh147/waapi-skill/issues/89) | #57 | 65 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 14 | `3f5b7464510f32b6f06dc4c6c3e0a7da700159ad07b8aff69b4b759bed41b9e1` |
| [`generic-core-media-build`](https://github.com/zcyh147/waapi-skill/issues/85) | #57 | 16 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 4 | `eb0692ad57f0a504bf110f38355997bb9abca7519ed412c4ed97c223a6a0decf` |
| [`generic-core-project-object`](https://github.com/zcyh147/waapi-skill/issues/84) | #57 | 55 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 19 | `caf467378cbabccb637cd93d18cc4e87e5356d409ce110da1f040825af4245ed` |
| [`generic-core-remaining`](https://github.com/zcyh147/waapi-skill/issues/86) | #57 | 43 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 13 | `a7541ae6dad3c8c033b13089c13c1faad9a2688aee985c72e5c414fdb812fa8a` |
| [`generic-core-runtime-inspection`](https://github.com/zcyh147/waapi-skill/issues/87) | #57 | 94 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 26 | `b66b1f4d66d8d77b456b98041c7e14fa2d383e02bae02b4a17fabfb85261d593` |
| [`generic-fixed-query-metadata`](https://github.com/zcyh147/waapi-skill/issues/96) | #57 | 47 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 11 | `b0d655fc0ea91c541e84ba8bdac59f56010d0b68da15aad86c5b3a6c360f47d9` |
| [`generic-host-ui-debug-waapi`](https://github.com/zcyh147/waapi-skill/issues/90) | #57 | 15 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 5 | `8d701d66442416c74f627e468842139fa8971b441b9b813be95cd9e7d3712ee0` |
| [`generic-soundengine-runtime`](https://github.com/zcyh147/waapi-skill/issues/88) | #57 | 124 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 26 | `5075fdcc32810059d6a3fee10499ff6823eea0be4c300dfb717bede6697c6ced` |
| [`generic-topics`](https://github.com/zcyh147/waapi-skill/issues/91) | #57 | 154 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 33 | `48f62fffb957f2ed581bee75cb11ddd6624411b77fc307813d1984b5ce015982` |
| [`named-authoring-ui-registration`](https://github.com/zcyh147/waapi-skill/issues/81) | #56 | 20 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 4 | `1b3b5a4a221d4ace2fcb897c15fc3f0076aea91a7c363831c02c043ef1942b52` |
| [`named-compound-undo`](https://github.com/zcyh147/waapi-skill/issues/83) | #56 | 5 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 1 | `a2d96ad477515f9533aff9f9dc5950b2f043100faf32cdf5d77b3abb1b3a4e85` |
| [`named-dangerous-debug-controls`](https://github.com/zcyh147/waapi-skill/issues/82) | #56 | 23 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 5 | `cf601f60fc5cddb76dd2468d16730b2929fed354bbadfee899a071f36c0777c8` |
| [`named-exact-artifact-code`](https://github.com/zcyh147/waapi-skill/issues/80) | #56 | 12 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 4 | `bc7b0e8add73f09f4eec32a7bc31e2ceb3ff04ca04673f77874ae91bfb8f33f1` |
| [`named-soundbank-planning`](https://github.com/zcyh147/waapi-skill/issues/79) | #56 | 18 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 4 | `c2e8f35304ea5f9cd60a34bd066c5eca3469dafcd0db39d75640fd95ccd72abc` |
| [`named-switch-assignments`](https://github.com/zcyh147/waapi-skill/issues/93) | #56 | 10 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 2 | `533beb07dfc66c994fe2a25b68f786b522fdce299b37c6c67d9a66c2683ddd23` |

## Already-deep and boundary evidence

| Classification | Disposition | Exact lanes | Audit evidence |
| --- | --- | ---: | --- |
| `generic-dedicated-route-boundary` | `prohibited_boundary` | 139 | request-schema rejects these exact URI lanes before construction and directs callers to the Registry-selected dedicated operation, preventing a weaker generic bypass. |
| `generic-fixed-command-audited-deep` | `already_deep` | 9 | The fixed command owns its selector/projection/result envelope and exposes no generic request-schema continuation; focused command tests seal its bounded read or metadata behavior. The object.get rows additionally inventory the preferred simple flags, the complete structured Builder contract, and the separately disclosed bounded advanced WAQL contract. |
| `generic-zero-input-audited-deep` | `already_deep` | 63 | The reflected request accepts no model-authored values; the Gateway owns the complete zero-input envelope, authorization/effect policy, dispatch, result bound, and any project guard. |
| `named-audio-import-audited-deep` | `already_deep` | 5 | The public audio-import-business/v1 contract exposes semantic kinds and stable declaration values, binds objects and fields live, derives native paths/types/order/batches/continuation, preserves media artifacts exactly, and has complete #54 five-version Program plus macOS/Windows Fresh and real-host evidence. |
| `named-internal-canonical-boundary` | `prohibited_boundary` | 5 | waapi.call is an internal canonical transaction representation, absent from normal operation discovery, and cannot accept a model-authored native request document. |
| `named-object-creation-graph` | `already_deep` | 17 | The public object-graph-business/v1 Adapters accept named hierarchy outcomes, plug-in roles, stable business fields, exact user artifacts, references, and RTPC points; bind opaque object, field, plug-in-type, control-input, and output-bus handles; compile exact Wwise types, paths, metadata scope/tokens, dependency order, batching, revisions, native requests, and the one Preview continuation inside the Gateway; and retain #78 five-version deterministic, exact macOS/Windows 2022.1 and 2025.1 real-host, and current-v3 Terra Fresh Agent Weather evidence. The pre-#78 Composer action vocabulary and normal fallback are removed. |
| `named-object-lifecycle` | `already_deep` | 25 | The public object-lifecycle-business/v1 Adapters expose only closed object or parent identities, conflict policy, and scalar outcomes; bind natural object paths to live GUID handles; derive every native request and Preview continuation inside the Gateway; remove the normal inline_typed surface; and retain #92 five-version Program, exact macOS/Windows real-host execution, and current-v3 Fresh Agent routing evidence. |
| `named-object-metadata-fields` | `already_deep` | 13 | The public object-metadata-business/v1 Adapters accept exact object identities, short user-facing field meanings, optional platform, and business outcomes; live discovery issues opaque field handles, compiles the exact metadata scope, token, wire value, request, and staged continuation inside the Gateway, and removes normal inline_typed ingress for all 13 lanes. #77 retains five-version deterministic repair and non-bypass coverage, exact macOS/Windows 2022.1 and 2025.1 real-host execution, and a current-v3 Terra Fresh Agent Alarm reference repair PASS plus identical verify-only audit on both hosts. |

Generated tests seal the native surface digest, every operation/version contract, and every public continuation. A new lane, field, version delta, or continuation therefore fails until this review policy and generated inventory are intentionally updated.
