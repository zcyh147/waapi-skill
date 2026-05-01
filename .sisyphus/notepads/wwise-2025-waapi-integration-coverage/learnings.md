
- Added the 2025.1 fail-closed contract by mirroring the 2024.1 pattern: `WWISE_2025_1_VERSION_KEY = "2025.1"`, build `2025.1.7.9143`, exact live paths, and immutable installed SampleProject root protection.
- The 2025.1 unit contract uses exact paths only and keeps bare `2025` unsupported; targeted and 2024 regression pytest gates both passed with evidence saved under `.sisyphus/evidence/`.

- Created the immutable `tests/_org/2025.1` fixture from `/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj`; the curated payload is 66 manifest files (README + `.wproj` + authored `.wwu`) with manifest digest `b37bb23fb0b982f6c1206c0edfbd99b0728ae8e9c09a4e72ed932c06840fc5a3`.
- The 2025.1 fixture inventory test must monkeypatch `live_environment.LIVE_VERSION_PATHS["2025.1"]` when using a temporary console, because 2025.1 exact-path validation runs before destructive immutable-source guards.

- Review fix: the 2025.1 fixture destructive guard test now uses a fake installed `SampleProject.wproj` under `tmp_path` and monkeypatches the 2025.1 exact-path contract plus immutable root, so unit coverage no longer depends on the real `/Applications` install while metadata provenance remains exact.

- Generated live 2025.1 manifest resources from the exact Wwise 2025.1.7.9143 console and SampleProject via the existing sandbox/headless reflection path; counts are 154 functions, 31 topics, 185 schemas, and 0 schema failures.
- The 2025.1 vs 2024.1 inventory records 6 added functions, 1 added topic, no removals, and schema/reflection changes for common APIs in `resources/manifest/2025.1/added-since-2024.1.json`.

- Added 2025.1 cross-version isolation audits without introducing semantic/coverage/deferred payloads: explicit 2025.1 dispatch reads `resources/manifest/2025.1`, default dispatch remains `2022.1`, bare `resources/manifest/2025/` payloads stay disallowed, and semantic source-note checks fail closed at the planned `resources/semantic/2025.1/source_notes.json` path.

- Grounded the 2025.1 semantic source-note bundle from NotebookLM notebook `wwise-2025.1-docs`: local notes now live under `references/semantic/2025.1/`, machine-readable gate data lives in `resources/semantic/2025.1/source_notes.json`, and the source-note checker allows all builder families for explicit `2025.1` only when the local gate is present.
- 2025.1 semantic caveats recorded: hierarchy naming is `Containers`, `Busses`, `Devices`, and `Property Container`; `object.structureChanged` is the preferred hierarchy topic; `getPropertyNames` is deprecated; `object.set` list data needs slot wrappers; soundbank size fields need generated SoundBanks before they are trusted.
- Verification for Task 5 passed: `python -m pytest tests/unit/test_2025_1_reference_layout.py -q` and `python -m pytest tests/unit/test_2025_1_cross_version_audit.py tests/unit/test_2025_1_version_isolation.py -q`. Evidence saved under `.sisyphus/evidence/task-2025-5-notebooklm-gate.txt` and `.sisyphus/evidence/task-2025-5-docs-fail-closed.txt`.

- Task 6 classified all 70 added/changed 2025.1 API inventory entries exactly once in `resources/coverage/2025.1/added-api-classification.json`: 7 read-only candidates, 14 sandbox-mutating candidates, 33 deferred, and 16 excluded; all entries remain non-behavior-tested planning classifications.
- The 2025.1 classification test uses a local mutation to prove `docs_reflection_mismatch` resolves to `deferred`, matching the discrepancy-register caveat that granular object hierarchy topics must not replace `object.structureChanged` proof.

- Task 7 generated the 2025.1 coverage/deferred/policy baseline for 154 reflected functions: 106 deferred, 48 excluded, and zero `live-tested`/`sandbox-mutating-tested`; 2024 status data is stored only as comparison metadata, not behavior proof.
- 2025.1 Task 6 candidate statuses are preserved as `candidate_status`/policy lists while coverage and matrix statuses remain deferred or excluded until later fresh live/destructive evidence tasks.

- Task 7 commit scope stayed clean by keeping the generated 2025.1 coverage resources, deferred registry, verification tests, evidence notes, and plan checkbox together while excluding `.sisyphus/runtime` and any auth/runtime artifacts.

- Task 8 hardened `tests/unit/test_2025_1_cross_version_audit.py` into the full 2025.1 parity guard: manifest, coverage, live matrix, phase2 summary, phase21 policy, deferred registry, source notes, versioned reference docs, and optional `resources/waql/2025.1/` resources now reconcile against the same 154 reflected functions.
- Fresh behavior promotion for 2025.1 now requires an approved 2025.1 root plus explicit fresh behavior text; local mutation tests reject stale 2022/2023/2024 proof, bare `2025` paths, manifest-only, skipped-test, helper-only, and NotebookLM-only evidence.

- Task 9 exact 2025.1 live read-only command passed with `WWISE_READINESS_TIMEOUT=180`; `ak.wwise.core.object.get` is now the only 2025.1 live-tested promotion, backed by `resources/waql/2025.1/object-get-live-matrix.json` plus eight per-case JSON evidence files under `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/live-read-only/`.
- 2025.1 WAQL hierarchy readback uses `\\Containers` rather than the 2024 `\\Actor-Mixer Hierarchy`; the 2025 matrix must use Containers for path, GUID placeholder, descendant, property, and return-option assertions.

- Task 10 added a separate 2025.1 destructive sandbox wrapper instead of changing the default dispatcher/runtime: opt-in/version/exact-path gates run before lock/prep, copied-sandbox target checks run before source hashing or launch, and immutable installed/tests/_org targets fail closed.
- Task 10 verification passed with `python -m pytest tests/unit/test_2025_1_destructive_safety.py -q`, the 2024 regression command, and focused 2025.1 live-environment/fixture regressions; evidence is saved under `.sisyphus/evidence/task-2025-10-*.txt`.

- Task 11 promoted ten fresh 2025.1 copied-sandbox destructive mutators: audio.import; object.create/delete/set; soundbank.setInclusions; switchContainer.add/removeAssignment; undo.begin/end/undo. Helper readbacks (`object.get`, `soundbank.getInclusions`, `switchContainer.getAssignments`) remain unpromoted unless separately behavior-tested.
- 2025.1 object creation under `\\Containers\\Default Work Unit` reads back `ActorMixer` creations as `PropertyContainer`, so destructive parity assertions must use 2025 readback semantics rather than 2024 `ActorMixer` type expectations.

- Task 12 docs contract now verifies 2025.1 parity wording from live resources: 154 reflected functions, one live-tested read-only URI, ten sandbox-mutating-tested URIs, and 143 deferred/excluded entries split as 95 deferred and 48 excluded.
- The 2025.1 review packet must keep Task 6 classification separate from behavior evidence: 70 added/changed entries, 59 functions, 11 topics, 7 added, 63 changed, with candidate statuses treated as review hints only.
- Docs/evals no-overclaim guards should avoid repeating forbidden Windows or support claims verbatim, even inside warning text or eval forbidden terms, because the contract scans user-facing surfaces as plain text.
