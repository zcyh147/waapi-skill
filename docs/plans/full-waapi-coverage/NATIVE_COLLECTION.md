# Native catalog collection for #175

The new discovery store is separate from the execution manifests. Reading or
publishing a native schema does not register a request, mutation, or Topic.
Until a matching capture is installed, native discovery reports missing evidence.
Ticket #175 remains incomplete until ten independently evidenced host/version
lanes (five versions on each host), shared-schema comparisons, and referenced definitions are reconciled.

For an already-running matching owned project, select an explicit isolated config
using the public `config-set` route, with the expected version and endpoint and
`read_only` modification policy. The collector never changes configuration or
starts Wwise. Run the Skill-local interpreter:

```bash
skills/waapi-skill/.venv/bin/python tests/maintenance/collect_authoring_core.py \
  --version 2025.1 --build 2025.1.7.9143 --host wwise-authoring \
  --config /absolute/isolated/config.json --output /absolute/new/capture-root
```

The historical collector filename is retained. `--version`, `--build`, and
`--host` are expected evidence identities, never live Gateway overrides. Every
native read passes through `run.py gateway.py`; the fixed direct-client command
collector is unchanged. Collection uses status, disclosed zero-input function
and Topic inventories, and one bounded `waapi-schema` read per inventory URI.
Every schema/inventory read must retain same-session getInfo attestation. Final
inventories and status reject changes during the capture, including equal-count
URI substitutions. Only matching-build packaged definition evidence is reused;
its source-file digest and complete graph travel with the capture. Missing or
unresolved definitions block a completed catalog, with raw receipts preserved.

The output contains exact Gateway receipts, stderr, and, only on completion,
`native-catalog.json`. It records host/build/session, source receipt hashes,
configuration hash, definitions, schemas and a complete-content digest. This is
reflection evidence only. The source project's full-tree hash/mtime and scoped
process cleanup remain the owning lifecycle's responsibility and must be sealed
alongside these receipts.

Offline discovery uses the existing commands:

```bash
skills/waapi-skill/.venv/bin/python skills/waapi-skill/scripts/run.py gateway.py \
  --version 2025.1 capabilities --native-host wwise-authoring --limit 20
skills/waapi-skill/.venv/bin/python skills/waapi-skill/scripts/run.py gateway.py \
  --version 2025.1 describe ak.wwise.ui.layout.getLayoutNames \
  --native-host wwise-authoring --full-schema
```

The directory returns a continuation for remaining rows. Complete schemas include
the exact same-build definition graph. In-scope unwrapped functions report
`missing_implementation`; only the two approved Authoring Lua/launch additions
receive `approved_exclusion`. Existing executable profiles remain independent.


Native and executable-profile selectors are mutually exclusive. Native directory
filters use the same namespace category and implemented semantic-family/route
facts as ordinary discovery; missing routes do not acquire a guessed family.
Compact rows omit source receipt detail, while `--detail` discloses provenance.
`describe --full-schema` retains source receipt digests plus catalog-bound JSON
pointers for the exact schema and definition graph. Branch enumeration and
business coverage completion remain owned by #176.

Native schemas are compared with the matching existing execution profile. An
exact difference is `native_schema_drift_pending_review`, even when the URI
already has an executable wrapper. Neither exact schema equality nor reflection
counts grant business execution evidence.

## Offline finalization of a complete failed capture

A capture that saved every schema but stopped on missing referenced definitions
can be completed without repeating native reads. Retain the original root and
its verdict. Supply an independent lifecycle owner's SHA-256 receipt seal and
matching installed definition attestation; the finalizer verifies each consumed
receipt, schema target, endpoint, host/build/session, initial/final inventories,
installed bundle version, executable digest and definition-file digest. It
writes only a new output root and records the original outcome and seal digest.

```bash
skills/waapi-skill/.venv/bin/python tests/maintenance/collect_authoring_core.py \
  --version 2025.1 --build 2025.1.7.9143 --host wwise-authoring \
  --finalize-from /absolute/immutable/capture/evidence/catalog \
  --receipt-seal /absolute/independent/capture-evidence-seal.json \
  --definition-attestation /absolute/installed-definition-attestation.json \
  --output /absolute/new/derived-catalog
```

This mode is offline and does not accept `--config`. The definition graph belongs
to the native catalog; it does not broaden the Console execution manifest. All
native spelling, including capital `OneOf`, remains intact. Recognizing these
branches and implementing their public behavior belongs to the subsequent
same-parent work, not reflection completion.

The reviewed Gateway parser seal now includes offline `--native-host` selectors,
mutual exclusion with execution profiles, and directory `--offset`. The first
full Program run retained two expected stale-seal failures (7001 passed, three
platform skips); the review policy and generated inventory were then refreshed.
That run is not passing gate evidence.

## Completed native input set (2026-10-17)

All ten host/version catalogs are packaged under
`skills/waapi-skill/resources/native-catalog/`, independent of execution
manifests. `index.json` pins each complete file; `capture-provenance.json` binds
its external lifecycle seal and original outcome. `definition-provenance.json`
records the independently checked installed sources of retained core definitions.
The two newer Authoring graphs additionally retain exact UI and WAFM documents
and their installed bundle/executable/source-file attestations.

| Build | Console functions / Topics | Authoring functions / Topics | Shared schemas, all exactly equal |
| --- | ---: | ---: | ---: |
| 2021.1.14.8108 | 99 / 27 | 99 / 27 | 126 |
| 2022.1.19.8584 | 112 / 32 | 112 / 32 | 144 |
| 2023.1.19.8928 | 149 / 32 | 149 / 32 | 181 |
| 2024.1.13.9056 | 148 / 30 | 170 / 34 | 162 |
| 2025.1.7.9143 | 154 / 31 | 179 / 35 | 169 |

`host-schema-parity.json` records every shared URI and exact source catalog
hashes, plus each host-only partition. All 782 shared schema pairs match. The
2024.1 and 2025.1 Authoring additions are respectively 38 and 41 functions plus
four Topics each; both versions omit 16 Console functions. This is independently
captured schema parity, not URI-based inference, execution credit, or a promise
about unexamined patch builds. The two approved Authoring Lua/launch exclusions
remain visible. All 48 previously missing ordinary Authoring version/schema rows
are now present, along with all shared schemas and referenced definitions.

Capture candidate was `3c8406f3f5748f4107f5a11c78094c850a728d39` on macOS;
Authoring used the packaged Windows executable through its shipped Wine runtime.
These are genuine Wwise reflection reads, not native-Windows host acceptance.
No Fresh Agent was launched. Root-owned lifecycle records preserve the full
source-project hashes/mtimes, owned process checks and port-release evidence.

- All five Console roots `console-2021-r1` through `console-2025-r1` completed
  reflection and cleanup using the existing scenario lifecycle. Their owned
  passing sandboxes were removed.
- Authoring `authoring-2021-r1` and `authoring-2022-r1` completed capture and
  cleanup. Authoring `authoring-2023-r1` completed its catalog but retained an
  original `BLOCKED` cleanup verdict from an immediate port-bind check; its
  independent seal separately records the subsequent bounded port-release
  guard, no residual processes, and unchanged source.
- Authoring `authoring-2024-r1` and `authoring-2025-r2` saved every schema and
  final inventory/status but retained original `BLOCKED` definition-closure
  verdicts. New derived roots complete them offline from externally sealed
  receipts and installed UI/WAFM source attestations. Original roots and
  verdicts remain intact; no schema was recollected to hide those failures.
- `waapi_ui_definitions.json` adds 20 definitions per newer lane;
  `wafm_definitions.json` adds 28 for 2024.1 and 32 for 2025.1. Capital `OneOf`
  remains native source data. Its branch semantics and all ordinary Authoring
  implementations remain obligations of [#176](https://github.com/zcyh147/waapi-skill/issues/176),
  [#188](https://github.com/zcyh147/waapi-skill/issues/188), and
  [#189](https://github.com/zcyh147/waapi-skill/issues/189), not claimed as
  business coverage by this catalog work.

## Maintainer launch and cleanup lessons

The first 2025 Authoring attempt never reached WAAPI. Its copied native-wrapper
option bundle (`--enable-alt-loader macdrv --wait-children`) did not reproduce
the wrapper parent's launch context. A separate root succeeded with the reduced
packaged Wine invocation: `start.exe /wait`, the explicit matching `Wwise.exe`,
and the exact private sandbox project. Private HOME/prefix, project identity
checks and source protection remained intact. Because all three added options
were removed together, the evidence attributes the failure to that bundle and
does not isolate an individual option as the cause. The failed attempt remains
sealed. Do not replace this observed route with app association or user-preference
copying based on that failure.

After terminating only owned processes, use the existing bounded
`wait_for_port_release` guard before judging the endpoint reusable. An immediate
bind check was premature in the 2023 run. Preserve that original verdict and
record later cleanup proof separately; do not relabel it as a clean first pass.
These are developer lifecycle lessons, not extra steps in Skill user workflows.

Final T01 focused validation ran the public native collector/discovery tests,
existing typed Gateway/catalog regressions, and the reviewed interface-depth
seal tests: **140 passed**. The root merger owns a fresh fixed Program gate on
the integrated T01 candidate before #175 closes. Broader Non-live remains the
combined substantial runtime PR gate. The earlier full Program result remains
7001 passed / 3 skipped / 2 stale-parser-seal failures, not a passing run.
