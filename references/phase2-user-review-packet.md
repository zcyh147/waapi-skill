# Wwise WAAPI Phase 2.1 user review packet

Use this packet when asking the user to approve the Phase 2.1 live sandbox coverage outcome. It summarizes what changed, what remains deferred, and what must not be claimed yet.

This packet is for Wwise 2022.1 Phase 2.1 coverage. Wwise 2023.1 support is separate and version-scoped. 2023.1 is supported only where resources, source notes, tests, and evidence exist under paths such as `references/semantic/2023.1/`, `resources/manifest/2023.1/`, `resources/semantic/2023.1/source_notes.json`, and `resources/coverage/2023.1/`. Do not use this 2022.1 packet to claim full 2023.1 WAAPI behavioral coverage.

For 2021.1 parity review, use `.sisyphus/evidence/wwise-2021-waapi-integration-coverage/parity-review-packet.md` when present with final reconciliation evidence. Current committed 2021.1 resources record 99 reflected functions with status counts supported 0, behavioral 0, deferred 43, excluded 46, live-tested 1, sandbox-mutating-tested 9, and unknown 0. Behavior evidence is limited to `ak.wwise.core.object.get` as the only live read-only URI and nine copied-sandbox mutating URIs: `ak.wwise.core.audio.import`, `ak.wwise.core.object.create`, `ak.wwise.core.object.delete`, `ak.wwise.core.object.setNotes`, `ak.wwise.core.soundbank.setInclusions`, `ak.wwise.core.switchContainer.addAssignment`, `ak.wwise.core.switchContainer.removeAssignment`, `ak.wwise.core.undo.beginGroup`, and `ak.wwise.core.undo.endGroup`. NotebookLM and source notes are source-only, not runtime proof, and the installed SampleProject is immutable source only.

For 2023.1 parity review, use `.sisyphus/evidence/wwise-2023-test-parity/parity-review-packet.md`. That packet records complete 2023.1 inventory/parity classification while keeping behavior evidence limited to one live read-only URI and ten copied-sandbox mutating URIs. Windows validation is recorded there as a non-blocking evidence caveat, not a hard gate.

For 2024.1 parity review, use `.sisyphus/evidence/wwise-2024-waapi-integration-coverage/parity-review-packet.md`. That packet records complete 2024.1 reflected inventory and parity classification for 148 functions while keeping behavior evidence limited to `ak.wwise.core.object.get` as the only live read-only URI and ten copied-sandbox mutating URIs. The remaining 137 entries stay deferred or excluded, readback helpers `ak.wwise.core.soundbank.getInclusions` and `ak.wwise.core.switchContainer.getAssignments` remain unpromoted, and Windows validation is recorded as a non-blocking evidence caveat, not a hard gate.

For 2025.1 parity review, use `.sisyphus/evidence/wwise-2025-waapi-integration-coverage/parity-review-packet.md`. That packet records complete 2025.1 reflected inventory and parity classification for 154 functions while keeping behavior evidence limited to `ak.wwise.core.object.get` as the only live read-only URI and ten copied-sandbox mutating URIs. The remaining 143 entries stay deferred or excluded, split as 95 deferred and 48 excluded. 2024 evidence is comparison metadata only, skipped live or destructive tests are opt-in gates rather than behavior proof, NotebookLM-only text is not runtime proof, and Windows validation remains a caveat and follow-up rather than macOS validation.

Exact 2021.1 opt-in command templates, for the separate 2021.1 support path, are:

```bash
WWISE_VERSION=2021.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" \
WWISE_LIVE=1 \
python -m pytest tests/live/test_2021_1_live_prerequisites.py tests/live/test_2021_1_reflection_prerequisites.py tests/live/test_2021_1_object_get_matrix.py -q

WWISE_VERSION=2021.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2021.1.14.8108/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2021.1.14.8108/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2021.1 \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive/test_2021_1_project_mutation_sandbox.py tests/destructive/test_2021_1_soundbank_audio_sandbox.py tests/destructive/test_2021_1_switchcontainer_assignment_sandbox.py -q
```

Exact 2023.1 opt-in command templates, for the separate 2023.1 support path, are:

```bash
WWISE_VERSION=2023.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" \
WWISE_LIVE=1 \
python -m pytest tests/live -q

WWISE_VERSION=2023.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2023.1 \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive -q
```

Exact 2024.1 opt-in command templates, for the separate 2024.1 support path, are:

```bash
WWISE_VERSION=2024.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" \
WWISE_LIVE=1 \
python -m pytest tests/live/test_2024_live_prerequisites.py tests/live/test_2024_reflection_inventory.py tests/live/test_2024_waql_live_matrix.py -q

WWISE_VERSION=2024.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2024.1 \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive/test_2024_project_mutation_sandbox.py tests/destructive/test_2024_soundbank_audio_sandbox.py tests/destructive/test_2024_switchcontainer_assignment_sandbox.py -q
```

Exact 2025.1 opt-in command templates, for the separate 2025.1 support path, are:

```bash
WWISE_VERSION=2025.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" \
WWISE_READINESS_TIMEOUT=180 \
WWISE_LIVE=1 \
python -m pytest tests/live/test_2025_1_live_prerequisites.py tests/live/test_2025_1_reflection_inventory.py tests/live/test_2025_1_waql_live_matrix.py -q

WWISE_VERSION=2025.1 \
WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2025.1.7.9143/Wwise.app/Contents/Tools/WwiseConsole.sh" \
WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2025.1.7.9143/SampleProject/SampleProject.wproj" \
WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes/2025.1 \
WWISE_READINESS_TIMEOUT=180 \
WWISE_LIVE=1 \
WWISE_DESTRUCTIVE=1 \
python -m pytest tests/destructive/test_2025_1_project_mutation_sandbox.py tests/destructive/test_2025_1_soundbank_audio_sandbox.py tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py -q
```

NotebookLM is source evidence generation or refresh only. Runtime reads local persisted evidence and source notes. 2021.1 NotebookLM and source notes remain source-only and are not runtime or behavior proof. 2025.1 evidence is version-scoped and limited to the committed 2025.1 resources, tests, and evidence packet.

## Before and after counts

| Metric | Count |
| --- | ---: |
| Reflected Wwise 2022.1 APIs | 144 |
| Functions | 112 |
| Topics | 32 |
| Original deferred before Phase 2 | 117 |
| Original deferred after Phase 2 | 63 |
| Original deferred promoted to behavioral coverage | 13 |
| Original deferred policy-approved as inventory only | 41 |
| Live behavioral covered count | 13 |
| Behavioral/live behavioral covered count | 13 |
| Fake-route inventory/substitute count (not behavioral) | 25 |

## Final status split

| Status | Count | Review meaning |
| --- | ---: | --- |
| `fake-route-tested` | 25 | Non-policy Phase 1 fake-route coverage remains inventory/substitute coverage only; it is not behavioral or live behavioral coverage. |
| `sandbox-mutating-tested` | 13 | Original deferred APIs promoted through copied-sandbox behavior evidence. |
| `skipped-approved` | 21 | `cli`, `core.remote`, and `debug` are user-approved inventory-only exclusions. |
| `wrapper-only` | 11 | `ui`, `ui.commands`, and `ui.project` keep wrapper diagnostics only. |
| `conformance-only-skip` | 11 | User-approved inventory and route conformance coverage only. It is not behavioral or live behavioral coverage. |
| `still-deferred-with-evidence` | 63 | Deferred entries have concrete blocker evidence and future review triggers. |

Do not claim that all 117 original deferred APIs are fully behavior-tested. The 25 fake-route-tested rows are inventory/substitute evidence only and do not contribute to behavioral or live behavioral counts. The original-deferred accepted split is 13 promoted behavioral, 41 policy-approved inventory-only, and 63 still deferred with evidence. The 41 original-deferred policy-approved inventory-only rows are 19 skipped-approved APIs, 11 wrapper-only APIs, and 11 conformance-only-skip APIs; the final status table has 21 skipped-approved rows because 2 skipped-approved rows came from fake-route-tested inventory/substitute evidence.

## Promoted APIs and statuses

The promoted Phase 2 live behavior is limited to the 13 original deferred APIs that reached `sandbox-mutating-tested`. These are copied-sandbox object, audio, SoundBank, and undo mutation flows with readback or generated-artifact evidence. They count as live behavioral coverage because they mutate only disposable sandboxes and include cleanup or source-immutability checks.

Read-only WAQL and object checks supply live evidence for their own suites, but they do not turn wrapper-only, skipped-approved, or still-deferred categories into live behavior.

## Exact conformance-only APIs

These 11 APIs are `conformance-only-skip`. They are inventory and route conformance coverage only, not behavioral or live behavioral coverage:

- `ak.wwise.core.project.loaded`
- `ak.wwise.core.project.postClosed`
- `ak.wwise.core.project.preClosed`
- `ak.wwise.core.project.save`
- `ak.wwise.core.project.saved`
- `ak.wwise.core.transport.create`
- `ak.wwise.core.transport.destroy`
- `ak.wwise.core.transport.executeAction`
- `ak.wwise.core.transport.prepare`
- `ak.wwise.core.transport.stateChanged`
- `ak.wwise.core.undo.cancelGroup`

## Still-deferred blockers

- Project lifecycle and transport lifecycle APIs in the conformance-only set remain policy-approved inventory coverage unless a future review asks for lifecycle or state-transition proof.
- `ak.wwise.core.undo.redo` is absent locally. `ak.wwise.core.undo.cancelGroup` is conformance-only under current policy, so it must not be promoted from the earlier sandbox rollback attempt.
- `ak.wwise.core.switchContainer.*Assignment` remains blocked because the disposable SwitchContainer/Switch Group fixture did not produce a materialized assignment readback pair.
- `ak.wwise.core.soundbank.processDefinitionFiles` remains blocked because the local definition-file fixture returned no usable SoundBank object readback and logged a file error.
- Transport, profiler, and soundengine cases remain blocked where no observable side effect was captured.

## Wrapper-only and skipped categories

`conformance-only-skip`, `wrapper-only`, and `skipped-approved` are inventory, conformance, or route-policy results, not live behavior. Keep UI shortcut categories as wrapper-only until a deterministic UI automation fixture is approved. Keep `cli`, `core.remote`, and `debug` skipped-approved under the current user policy.

## WAQL gaps

Keep WAQL generation fail-closed for escaping beyond normal JSON string escaping, exhaustive object-type property and reference inventories, malformed-WAQL error payload shapes, timeout, memory, recursion, and performance limits, plus mutation semantics. The available WAQL evidence covers bounded read-only object queries only.

## Profiler and soundengine feasibility notes

Profiler, transport, and soundengine coverage must not be promoted from accepted calls alone. Local evidence did not observe a transport state transition, a profiler capture-log payload for `postMsgMonitor`, or profiler game-object payloads for game-object registration. Returned ids, empty mappings, capture start/stop, no exceptions, or accepted calls are not enough to count as coverage.

## Windows-pending language

Windows validation remains pending. macOS-generated `GeneratedSoundBanks/Windows` artifacts prove only that the macOS sandbox generated a Windows-named output folder. They are not Windows-host evidence and must not be described as cross-platform validation.

## Approval gate text

Use this exact approval gate before F1-F4 are marked complete:

```text
Please review the Phase 2.1 live sandbox coverage packet and confirm whether you approve the remaining 63 still-deferred-with-evidence entries, the 21 skipped-approved entries, the 11 wrapper-only entries, the 11 conformance-only-skip entries, and the Windows-pending status. F1-F4 must not be marked complete until you explicitly approve this packet.
```

If the user does not explicitly approve, keep F1-F4 open and record the missing approval in `.sisyphus/evidence/task-12-approval-stop.md`.
