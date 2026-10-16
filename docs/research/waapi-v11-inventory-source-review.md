# v1.1 inventory source review

This review reconciles the approved repair spec (#163) with current public
contracts before regenerating the interface-depth and branch-audit artifacts.
It does not promote a declared route, selector mapping, or historical test into
current branch execution credit.

## Reviewed semantic changes

| Area | Reviewed change | Contract boundary / evidence |
| --- | --- | --- |
| Connection selection (#165) | Live commands and Drafts use explicit persistent config; root host/port flags and connection environment overrides no longer select the endpoint. Version flags are offline inspection only. Persisted Draft/transaction bindings reject endpoint/version/config-path drift. | `test_gateway_connection_binding.py`; root parser flags must be sealed as well as subcommands. |
| Metadata discovery (#166) | Paged complete enumeration and exact detail selection supplement lexical discovery. Page and selection locators are Gateway-derived, read-only and scope-bound; they do not authorize mutations. Full metadata and units remain disclosed through the exact selection path. | `test_metadata_selection_gateway.py`, `test_metadata_discovery_gateway.py`, `metadata_discovery.py`. |
| Conditional fields (#167) | Reference prerequisites are derived from reviewed metadata; atomic object.set activation differs from separate confirmed prerequisite edits on object.setReference. Unsupported expressions/cycles/conflicts remain fail-closed. | `test_conditional_reference_gateway.py`; `tests/ATTENUATION_NATIVE_ACCEPTANCE.md` distinguishes all-five override activation from 2025.1-only native false-routing evidence. |
| GameParameter creation (#168) | Reviewed class-scoped Min/Max prerequisites may use matching live built-in-parameter defaults in one creation call. Arbitrary classes and dependency grammars retain the staged boundary. | `new_object_defaults.py`, `test_gameparameter_class_fields_gateway.py`; public native candidate `90018ae0` has five-version evidence for Min=-12/Max=36/InitialValue=7. |
| ShareSet creation (#169) | WorkUnit child placement is separate from owner Effect/Source topology, with live Type Handles, target preflight, result binding and independent verification. | `operation_plugin.py`, `test_plugin_shareset_gateway.py`; 2022.1–2025.1 public native candidate `df8e0610`. 2021.1 remains a packaged boundary; the classic name encoding failed, and alternative native topology is unresolved. |
| Recovery (#170) | Gateway-owned failure state determines whether a bounded read/discovery or declared correction is safe. Retryability must not be inferred from a generic command name or successful metadata read alone. | `recovery.py`, `test_policy_recovery_gateway.py`; unknown mutation outcomes remain distinct from failures proven before write. |
| Persistence (#171) | Ordinary project edits and generated outputs are retained. Resource-pair cleanup, UI registration inverse relationships, terminal host safety facts and non-reversibility remain explicit. Historical artifacts retain their hashes and final agent_result. | `transaction_cleanup.py`, `test_persistent_project_cleanup_gateway.py`, existing UI/paired/terminal regressions. |
| Compact discovery | After successful object.set field discovery, the repeated discovery menu points to the existing exact draft-inspect continuation. Full returned metadata and both declaration routes remain available, under the unchanged 7000-byte regression. | `test_object_graph_business_gateway.py::test_object_set_discovers_two_business_field_meanings_in_one_revision`. |

No reflected native URI was added or removed by these repairs. Later positive
ShareSet evidence does not erase the failed 2021.1 probe or the original frozen
business baseline. A normal unsupported public response is not native
unavailability evidence.

## Audit-tool corrections included in this reconciliation

The parser seal now records root options as a separate `<root>` contract.
Previously it covered subcommands only despite its all-public-flags wording.
The focused regression proves both offline version aliases are present and
removed root host/port flags are absent; business config and execution tests
remain responsible for semantic eligibility.

A selector policy now joins a schema occurrence only when its full reflected
schema digest matches the policy's declared version/profile schema. Equal URI
and JSON pointer alone are insufficient. A differing overlay retains an explicit
`profile_schema_mismatch` finding instead of inheriting a Console disposition.
The occurrence index and expected profile hashes are checked for drift. Residual
groups use each occurrence's schema digest, not a union of potentially different
profile schemas.

Metadata `page` and `selection` values are reviewed as Gateway-derived locator
values in fixed-command ownership accounting. They remain distinct from
caller-authored stable scalars and mutation Field Handles.

## Regeneration rules

Update the reviewed source-contract hashes only after the final runtime merges.
Use the existing `generate_interface_depth_inventory.py` producer and its
`--check`, followed by `branch_coverage_audit.py` and its `--check`. The branch
checker compares the renewed review seals directly with current registries.
`--require-complete` must continue to exit 2 while unproved business alternatives
remain, even when every generated artifact is reproducible.

The before/after source seals and exact structural deltas are recorded with the
completed regeneration below. Functional PASS counts belong to actual completed
runs, not this source review.

## Completed source-seal comparison

Runtime review base: `4dd1fa24`. The source review leaves the reflected native
surface identity unchanged. The continuation hash covers declared command
contracts and query layers, not every dynamically returned phase projection;
those retain separate Gateway regressions and branch-audit source digests.

| Seal | Previous reviewed value | Reconciled value |
| --- | --- | --- |
| `gateway_parser_sha256` | `41e31e13abb6f5e907296ad877755879d61afbf0114c6d49f80d84c358b1583e` | `7f47db965914bc7af6d2947742fc0e2a67d9bb3582f281b72e0d829573d09440` |
| `operation_contract_sha256` | `5e937223e22489a6619669834455091ba4eacf56a975d3eae3f57c048d9d0bca` | `206b88bf1d1810dbe876745c0c952208b965b92b0e74d69b3ba93878e0243617` |
| `public_continuation_sha256` | `a8db4713bb16a7a62a944ffbc15b9e63e6892fb6581cd73e600a52151f8ac8fc` | `2904c6b6e9f45047ba553e786cf3cf4f2424a54edbf67e0f8d5f6180205ded11` |
| `typed_request_surface_sha256` | `cbdccf1679c6f534b501cf3f67b503c376fa6a155d0cf8f085306ad86c0a031c` | `cbdccf1679c6f534b501cf3f67b503c376fa6a155d0cf8f085306ad86c0a031c` |

No native or named-operation lane identity changed: 849 native rows and 153
named operation/version rows remain. The changed named public contract rows are:

- `object.setReference@2021.1`: `32e6c21571dd6efa17cad7b5efbc24c0ec24a219e96db156f6246a047f5e653e` → `4f13975b39f9bb92c3ac75313b819945a304a40fd310f387798d880a9978b633`.
- `object.createPlugin@2022.1`: `463d06569d9bbbf665200dbfbee3d662d201ba41fa310f94f19ad636a688dbf0` → `43570f9da7647b5a67d4e1c28a4c930951ae036d245d96787b82874a9c4bec15`.
- `object.setReference@2022.1`: `1b916552173937ef2b234b95be30e320733fcee1a95a3fd9a7d8c9d6396a80de` → `2685bfbe2ed7428a942337cb2a227641057a9f3f6f7884a8d9a8308d5d120eac`.
- `object.createPlugin@2023.1`: `eee5b29b1093be9fca5822370de9bd0cada746f78365148791dba88ab43ce055` → `53fffce82e2b8bc5c29e7b212049f61406f8fe418f775155bcd37d45a4ef3d08`.
- `object.setReference@2023.1`: `48eee4c941eb2f86c60a8ebbfe07a9ed5f972441296320f7435df820e4fab78e` → `ca73e8be418e6cc0fb640446922e1492e04ec1c66a9b10595c7b840bd34af20e`.
- `object.createPlugin@2024.1`: `7bc3940d45b9b55656ef6837af91c97902aee980c51586520300b611c839f273` → `8c844624e186ef3f8be656f974515100e89954d21a1d3c7822548867b440fe5e`.
- `object.setReference@2024.1`: `135d08ff8c1be057e838c141f4bf204b54a962c49077e88d6e4e36cdbef60c5b` → `c30f1516bdcb6838d850be9aa2d7d9b2d84cbe6ad7f85ba61e9c9a5c450bb5f3`.
- `object.createPlugin@2025.1`: `eef94b88aab61ce499464001c0c22e7a80f040b0bbdebabdd5b7f8a83eaa47e3` → `558b637a45360f4546dea51cf46349ef550b8914c436f960a4605a7f28b2a7e8`.
- `object.setReference@2025.1`: `5f0f096a7cc629af07fdb4286c2e3ca9a524a3967541576cee494bdafd6c6621` → `24d96cfc6484abd2b9b0774581814408abaa73dd151a093b072a67bfb289f4ae`.

The new metadata locator ownership is reviewed as Gateway derivation, while
its page-size scalar remains user-selectable. Group audit descriptions now name
placement, dependency and resource-lifecycle limits instead of granting all
business combinations inherited family credit.

Fixed/native field-contract hashes changed on 25 versioned rows, covering
`ak.wwise.core.object.getAttenuationCurve`, `ak.wwise.core.object.getPropertyAndReferenceNames`, `ak.wwise.core.object.getPropertyInfo`, `ak.wwise.core.object.getTypes`, `ak.wwise.core.object.isPropertyEnabled`.
The interned field-contract table has 196 records and the named argument-contract table has 35 records. These are structural counts, not functional passes.

Focused validation completed on this reconciliation: 27 passed in 245.71s
(`test_interface_depth_inventory.py` and `test_branch_coverage_audit.py`). Both
existing producers' `--check` commands returned 0. The branch audit remains
structurally consistent and behavior coverage remains incomplete; its CLI test
continues to require exit 2 from `--require-complete`. These maintainer checks
launch neither Wwise nor Fresh and add no functional execution credit.
