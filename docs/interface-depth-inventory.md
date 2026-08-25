# Interface-depth inventory

This report is generated from the exact five-version public surface and the reviewed policy in `interface-depth-review-policy.json`. The 824-lane construction baseline proves typed request construction only; it is not evidence that every interface is deep.

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
| `generic-cli-console` | #57 | 65 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 14 | `3f5b7464510f32b6f06dc4c6c3e0a7da700159ad07b8aff69b4b759bed41b9e1` |
| `generic-core-media-build` | #57 | 16 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 4 | `eb0692ad57f0a504bf110f38355997bb9abca7519ed412c4ed97c223a6a0decf` |
| `generic-core-project-object` | #57 | 55 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 19 | `caf467378cbabccb637cd93d18cc4e87e5356d409ce110da1f040825af4245ed` |
| `generic-core-remaining` | #57 | 43 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 13 | `a7541ae6dad3c8c033b13089c13c1faad9a2688aee985c72e5c414fdb812fa8a` |
| `generic-core-runtime-inspection` | #57 | 99 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 27 | `626e63d839946e5d4d04414cd091e01b9dd3e3548c3c3dfc26302f7ccfa27ae1` |
| `generic-host-ui-debug-waapi` | #57 | 17 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 6 | `defe5e45b8e2d225ff58c0d2903acf1c7cca078770799783054180a63b8afdc2` |
| `generic-soundengine-runtime` | #57 | 124 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 26 | `5075fdcc32810059d6a3fee10499ff6823eea0be4c300dfb717bede6697c6ced` |
| `generic-topics` | #57 | 154 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 33 | `48f62fffb957f2ed581bee75cb11ddd6624411b77fc307813d1984b5ce015982` |
| `named-authoring-ui-registration` | #56 | 10 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 2 | `7cd800c227390e0494e8e20ff1a96742599091a02f53e3fda9eb27ba4961e221` |
| `named-compound-undo` | #56 | 5 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 1 | `a2d96ad477515f9533aff9f9dc5950b2f043100faf32cdf5d77b3abb1b3a4e85` |
| `named-dangerous-debug-controls` | #56 | 13 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 3 | `ddd48cfeb2bdc04bbdaa438d9605640b583fb4ddde5956847736b7e7abb6dfb0` |
| `named-exact-artifact-code` | #56 | 12 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 4 | `bc7b0e8add73f09f4eec32a7bc31e2ceb3ff04ca04673f77874ae91bfb8f33f1` |
| `named-object-creation-graph` | #56 | 17 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 4 | `a1eef3587d862bfd6a34a26da9c8856e0366354995186a3792eed7148fb12622` |
| `named-object-metadata-fields` | #56 | 13 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 3 | `d9ac4123421b0686fd97518ac1ee7aae487266869f7f03a7c6146c2421e7aebd` |
| `named-soundbank-planning` | #56 | 14 | 2021.1, 2022.1, 2023.1, 2024.1, 2025.1 | 3 | `353e5de69a0a831633bffcf74794f10ddca298177df144e2c693bff2411bc750` |

## Already-deep and boundary evidence

Named operations classified `already_deep` already accept closed business selectors/scalars or exact user artifacts without a model-authored construction plan. `audio.import` is the proved business-declaration reference Adapter. Generic rows behind a dedicated operation are a prohibited bypass boundary; the internal `waapi.call` representation is not public. Pure fixed commands and zero-input native lanes have no model-authored native request structure.

Generated tests seal the native surface digest, every operation/version contract, and every public continuation. A new lane, field, version delta, or continuation therefore fails until this review policy and generated inventory are intentionally updated.
