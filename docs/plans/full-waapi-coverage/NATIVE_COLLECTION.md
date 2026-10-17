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
