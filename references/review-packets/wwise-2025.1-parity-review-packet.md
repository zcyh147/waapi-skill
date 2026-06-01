# Wwise 2025.1 parity review packet

Use this packet for final Task 14 review of the 2025.1 parity evidence. The 2025.1 reflected function inventory and parity classification reconcile to 154 functions. Behavior evidence is intentionally narrower: one live read-only URI and ten copied-sandbox mutating URIs have explicit fresh 2025.1 evidence. Manifest reflection proves inventory only. Manifest reflection, 2024 comparison metadata, skipped live tests, skipped destructive tests, helper-only readbacks, and NotebookLM-only notes are not 2025.1 behavior proof.

## Promoted Evidence

Promoted live read-only evidence is limited to:

- `ak.wwise.core.object.get`, promoted to `live-tested` from Task 9 fresh 2025.1 read-only WAQL/live matrix evidence.

Promoted copied-sandbox mutation evidence is limited to these ten URIs from Task 11 fresh 2025.1 copied-sandbox destructive evidence:

- `ak.wwise.core.audio.import`
- `ak.wwise.core.object.create`
- `ak.wwise.core.object.delete`
- `ak.wwise.core.object.set`
- `ak.wwise.core.soundbank.setInclusions`
- `ak.wwise.core.switchContainer.addAssignment`
- `ak.wwise.core.switchContainer.removeAssignment`
- `ak.wwise.core.undo.beginGroup`
- `ak.wwise.core.undo.endGroup`
- `ak.wwise.core.undo.undo`

Task 11 readback helpers, including `ak.wwise.core.object.get`, `ak.wwise.core.soundbank.getInclusions`, and `ak.wwise.core.switchContainer.getAssignments`, can appear in evidence but remain unpromoted unless their own URI behavior was separately tested. Helper readbacks are support checks, not promoted behavior entries.

## Deferred/Excluded

The 2025.1 parity resources keep 143 entries deferred or excluded after the one live read-only and ten copied-sandbox mutation promotions. The current split is 95 deferred entries and 48 excluded entries. Risky families remain excluded or deferred, including soundengine, profiler, transport, UI, CLI, remote, debug, source-control, work-unit, and other entries without fresh behavior evidence.

Deferred and excluded entries remain governed by `resources/coverage/2025.1/api-coverage.json`, `resources/coverage/2025.1/live-coverage-matrix.json`, and `resources/deferred/2025.1.json`. Do not promote them from manifest reflection, 2024 comparison metadata, skipped live tests, skipped destructive tests, NotebookLM-only notes, or helper-only readbacks.

## 2025-Only Classification

Task 6 classification is a 2025.1 planning and source-note classification, not behavior evidence. It covers 70 added or changed 2025.1 inventory entries: 59 functions and 11 topics, with 7 added entries and 63 changed entries. The classification split is 33 deferred, 16 excluded, 14 candidate-sandbox-mutating, and 7 candidate-live-read-only.

Candidate statuses are review hints only. They do not count as 2025.1 live-tested or sandbox-mutating-tested until a later task records fresh 2025.1 behavior evidence and updates the coverage resources.

## NotebookLM and Docs Caveats

NotebookLM notebook `wwise-2025.1-docs` was used to generate or refresh persisted local source notes only. Runtime builders and reviews must read local resources such as `references/semantic/2025.1/` and `resources/semantic/2025.1/source_notes.json`; they must not query NotebookLM at runtime or treat NotebookLM-only text as WAAPI behavior proof.

Task 5 caveats remain active: 2025.1 hierarchy labels are `Containers`, `Busses`, `Devices`, and `Property Container`; `ak.wwise.core.object.structureChanged` is the preferred hierarchy-change topic; `ak.wwise.core.object.getPropertyNames` is deprecated in favor of `ak.wwise.core.object.getPropertyAndReferenceNames`; `ak.wwise.core.object.set` list assignments need slot wrappers; SoundBank size fields need generated SoundBanks before they are trusted; and public-library URL paths recorded from NotebookLM are evidence candidates, not fetched proof. URL candidates are not fetched proof unless separately archived.

## Commands Run

Default Wwise-free suite command:

```bash
python -m pytest -q
```

Task 9 live read-only command:

```bash
WWISE_VERSION=2025.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" WWISE_READINESS_TIMEOUT=180 WWISE_LIVE=1 python -m pytest tests/live/test_2025_1_live_prerequisites.py tests/live/test_2025_1_reflection_inventory.py tests/live/test_2025_1_waql_live_matrix.py -q
```

Task 11 destructive sandbox command:

```bash
WWISE_VERSION=2025.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2025.1 WWISE_READINESS_TIMEOUT=180 WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 python -m pytest tests/destructive/test_2025_1_project_mutation_sandbox.py tests/destructive/test_2025_1_soundbank_audio_sandbox.py tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py -q
```

Task 12 docs contract command:

```bash
python -m pytest tests/unit/test_2025_1_docs_contract.py tests/unit/test_eval_metadata.py -q
```

Task 9 live read-only result: fresh 2025.1 `ak.wwise.core.object.get` evidence recorded in `.sisyphus/evidence/task-2025-9-live-read-only.txt` and `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/live-read-only/`.

Task 11 destructive result: `5 passed in 344.82s (0:05:44)`, with fresh copied-sandbox evidence recorded in `.sisyphus/evidence/task-2025-11-destructive-sandbox.txt` and `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/destructive/`.

## Task 14 Final Reconciliation

Task 14 reran the final 2025.1 reconciliation commands and retained the scoped evidence model:

- Focused 2025 audit: `48 passed in 0.23s`.
- Exact 2025 live command: `12 passed in 170.38s (0:02:50)`.
- Exact 2025 destructive command: `5 passed in 400.56s (0:06:40)`.
- 2024 regression command: `26 passed in 0.11s`.
- Default Wwise-free suite: `646 passed, 57 skipped in 1.79s`.
- JSON resources validated by Python parsing: coverage, live matrix, phase2 summary, phase21 policy, deferred registry, added-api classification, WAQL matrix, and eval metadata.
- Final counts: 154 reflected functions; 154 coverage entries; 154 live-matrix entries; 154 phase2 summary entries; 143 deferred/excluded entries; status split `excluded=48`, `deferred=95`, `sandbox-mutating-tested=10`, `live-tested=1`.
- Promoted evidence remains limited to `ak.wwise.core.object.get` plus the ten copied-sandbox mutating URIs listed above. `ak.wwise.core.soundbank.getInclusions` and `ak.wwise.core.switchContainer.getAssignments` remain deferred helper readbacks.
- Runtime artifact checks found no tracked or staged `.sisyphus/runtime` files; details are recorded in `.sisyphus/evidence/task-2025-14-no-runtime-artifacts.txt`.

## Source Immutability

Task 11 ran through the 2025.1 destructive sandbox runtime with copied SampleProject sandboxes under `WWISE_SANDBOX_ROOT`, unique WAAPI names, readback or state assertions, cleanup, and source immutability checks. Destructive tests require explicit `WWISE_VERSION=2025.1`, exact 2025.1 console and SampleProject paths, `WWISE_LIVE=1`, `WWISE_DESTRUCTIVE=1`, and copied-sandbox targets.

The destructive safety gates fail closed. Missing opt-in variables stop before sandbox preparation and before WwiseConsole launch. Active targets under `tests/_org/2025.1` or the installed SampleProject are rejected.

## Windows Caveat

Windows validation is a caveat and follow-up for this 2025.1 parity packet. The accepted Task 9 and Task 11 evidence was captured on macOS. macOS-generated artifacts, including any `GeneratedSoundBanks/Windows` output folder, are not Windows-host validation and must not be described as cross-platform proof.

## Known Non-Goals

- Do not claim every 2025.1 API is live-tested.
- Do not claim broad 2025.1 behavior support.
- Do not claim manifest reflection proves behavior.
- Do not claim 2024 evidence counts as 2025.1 proof.
- Do not claim skipped live or destructive tests are behavior evidence.
- Do not promote `ak.wwise.core.soundbank.getInclusions` or `ak.wwise.core.switchContainer.getAssignments` from readback-helper use.
- Do not treat NotebookLM-only text as runtime behavior proof.
- Do not describe macOS evidence as Windows-host validation.
- Do not change coverage or deferred classifications as part of this docs packet.
- Do not run live or destructive Wwise commands for Task 12.
