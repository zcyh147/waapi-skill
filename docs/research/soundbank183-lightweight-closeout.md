# #183 lightweight functional acceptance — 2026-10-27

The owned #183 scope is ready for closure under the
[approved acceptance policy](../plans/full-waapi-coverage/SPEC.md#user-approved-lightweight-wrapper-acceptance--2026-10-27).
The required #179 Conversion setter component is delivered. Main should remove
the fulfilled **#183 → #179** native blocking edge before closing #183, while
retaining a normal reference to #179's remaining plugin work. This note performs
no issue action and does not close #179 or parent #174.

This is a documentation-only successor assessment at `c5ba64e5`. It reuses
retained source, program controls and exact native packets. No tests, native
calls, generators, accessor research or additional QA ran for this closeout.

## Closed inputs and code controls

The existing [business schemas](../../skills/waapi-skill/wwise_waapi/soundbank_business_contracts.py),
[compiler](../../skills/waapi-skill/wwise_waapi/soundbank_business.py) and
[versioned plans](../../skills/waapi-skill/wwise_waapi/operation_soundbank.py)
own generation, inclusions, external conversion and Definition inputs. They
retain named/temporary/all-user SoundBanks; nested Event/AuxBus/inclusion choices;
platform/language selection; default omission versus explicit empty/false;
rebuild/cache/Init choices; and an explicit memory-generation result-only boundary.
The applicable Core and CLI routes retain their version-specific contracts.
Core Definition and external-source functions are absent in the pinned 2021.1
reflection; their later routes do not borrow an invented older shape.

Inputs and outputs remain within declared I/O scope. Hashed input files,
exact bound identities, configuration, the three modification policies,
immutable Preview, drift refusal, one execution, bounded diagnostics and output
preservation remain enforced. Existing negative controls cover invalid inputs,
ambiguous/wrong identities, changed input/output bindings and native failures.
These are shared wrapper controls, not a claim to have exercised every licensed
plug-in, native failure or parameter value.

Representative public controls are retained in
[test_soundbank_business_gateway.py](../../tests/unit/test_soundbank_business_gateway.py),
[test_operation_soundbank_version_matrix.py](../../tests/unit/test_operation_soundbank_version_matrix.py),
[test_soundbank_process_definition_plan.py](../../tests/unit/test_soundbank_process_definition_plan.py)
and [test_soundbank_native_witness.py](../../tests/unit/test_soundbank_native_witness.py).
The [recorded focused runs](../../tests/TEST_INVENTORY.md#2026-10-27-183-core-file-workflows-and-definition-coverage)
include 115 Definition checks, four seal/policy/admission checks and two
producer-to-persisted-writer controls. The later output correction has
[22 recorded focused checks](../../tests/TEST_INVENTORY.md#2026-10-27-183-configured-external-output-correction).
These overlapping, candidate-attributed selections are not a summed full gate.

## Definition and Short-ID acceptance

The [table-import policy](../plans/full-waapi-coverage/SPEC.md#user-approved-lightweight-table-audio-acceptance--2026-10-27)
accepts complete wrapping and code controls. Ordered distinct input files,
repeated banks/object rows and documented GameSync exclusions remain selectable.
Complex/nonempty-prestate/exclusion inputs disclose result-only verification
before authorization; simple empty-before inputs retain exact inclusion checks.
No unobserved merge, removal or exclusion effect is claimed.

The current resolver already uses version-aware `short_id_query(..., unique=True)`
with exact uint32 Short ID, GUID, uniqueness and expected-type checks. The retired
unversioned table is not current code. The
[R89 reconciliation](../plans/full-waapi-coverage/tickets/09-complete-soundbank-definition-conversion-and-build-options.md#r89-current-source-reconciliation--2026-10-23)
and existing public wrong-type/ambiguity controls satisfy this item; no new
Definition native/Fresh run is required.

## Retained artifact evidence

The following are separate scoped outcomes on macOS WwiseConsole
2025.1.7/build 9143. Their original verdicts remain intact.

| Mechanism | Retained outcome and actual artifact | Identity/source/cleanup scope |
| --- | --- | --- |
| Core audio.convert | `e6bb933f`, `soundbank183-core-files-2025-r1`: independent 11,230-byte WEM, SHA-256 `56fa957ec1c90b60d78e19e7078d1a55a52da3a00f810a151c706ba3e81a8b0c`; Gateway status remains `result_schema_checked`. | Exact Sound/active Source and input preservation passed. |
| Temporary Bank generation | Same root: independently proved 34,308-byte Bank, SHA-256 `4a1e6d5d246bf139e0bae09841059563d994c65335c538df98cee0fc83abfe5c`; its transaction was verified. | Bank identity and inputs preserved. |
| Omitted-output external conversion | Corrected `451647cd`, `soundbank183-external-fixed-2025-r1`: **PASS, 4.78s**, one verified transaction and a 1,696-byte WEM, SHA-256 `765f0b49ad5beb63011b7bf4f996a780dbe4dff0dd24a6bbfa0fc649c7081c5b`. | Exact live platform-specific Project.ExternalSourcesOutputPath was sealed/revalidated; source/input hash, tree and mtime preserved, processes cleaned, passing sandbox deleted. |

The original three-effect `e6bb933f` node remains **FAIL, 7.71s** because its
external-output expectation failed. The first two scoped successes are reused;
the failed-only external correction supplies the missing effect independently.
This is cumulative mechanism acceptance, not a regraded combined PASS.
The original failed root and quarantined sandbox remain unchanged.

Exact retained assessment paths are
`.waapi-skill-state/full-coverage/soundbank183-core-files-2025-r1/main-assessment.json`
and
`.waapi-skill-state/full-coverage/soundbank183-external-fixed-2025-r1/main-assessment.json`.
The [Test Inventory](../../tests/TEST_INVENTORY.md#2026-10-27-183-configured-external-output-correction)
records the original observation digests, output-path repair and cleanup scope.

## Delivered Conversion setter component

Reviewed `2a6a8fbd877cd895e896091a7c5379f53e4538f8`, integrated in `c5ba64e5`,
completes the closed 2024.1/2025.1 setter at the accepted boundary. Exact
Conversion identity, live project platform and discovered installed Conversion
Type Handle are bound and revalidated through normal policy, immutable Preview
and one execution. An old stronger Preview requires recreation.

The schema and Preview disclose `result_schema_checked`, `verified=false`,
`business_state_verified=false`. The setter returns no codec identity and creates
no automatic scalar continuation. Actual replacement, platform-to-codec GUID
association and other-platform preservation remain unverified. Accepted getter
ambiguity and unexercised setter effects do not block this scope. Exact chosen-GUID
field configuration remains a separate ordinary Field Handle operation.

The retained repair record has 26 Gateway/collector checks, seven selected setter
program rows and three adapter cases, all passing on the frozen repair; it adds
no native effect claim. The [Conversion note](conversion-plugin-placement-179.md)
describes the public boundary and preserves the original failed/blocked native
observations. #179's remaining older Sink/Metadata construction and plugin
placement accounting is separate: this closeout makes no unsupported native
absence inference and leaves that issue open.

The local audit archive in the closeout worktree is
`.waapi-skill-state/full-coverage/soundbank183-lightweight-closeout-audit/`.
Its manifest binds copied reports and retained assessment bytes to their original
paths and SHA-256 values; originals were preserved. #195 retains final global
mapping and stable combined Program/Non-live gates. #194 Fresh budget remains
zero. No Windows or five-version native matrix acceptance is added.
