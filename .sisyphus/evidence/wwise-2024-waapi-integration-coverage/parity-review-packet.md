# Wwise 2024.1 parity review packet

Use this packet for Task 11 review of the 2024.1 parity evidence. The 2024.1 reflected inventory and parity classification reconcile to 148 functions, but behavior evidence is intentionally narrower: one live read-only URI and ten copied-sandbox mutating URIs have explicit 2024.1 evidence. Manifest reflection proves inventory only. Manifest reflection, skipped live tests, and skipped destructive tests are not behavioral proof.

## Promoted Evidence

Promoted live read-only evidence is limited to:

- `ak.wwise.core.object.get`, promoted to `live-tested` from the Task 8 read-only WAQL/live matrix evidence.

Promoted copied-sandbox mutation evidence is limited to these ten URIs from Task 10:

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

Task 10 readback helpers, including `ak.wwise.core.soundbank.getInclusions` and `ak.wwise.core.switchContainer.getAssignments`, can appear in evidence but remain unpromoted. They are support checks, not promoted behavior entries.

## Deferred/Excluded

The 2024.1 parity resources keep 137 entries deferred or excluded after the one live read-only and ten copied-sandbox mutation promotions. Risky families remain excluded or deferred, including soundengine, profiler, transport, UI, CLI, remote, and debug families.

Deferred and excluded entries remain governed by the 2024.1 coverage and deferred resources. Do not promote them from manifest reflection, skipped live tests, skipped destructive tests, or helper-only readbacks.

## Commands Run

Default Wwise-free suite command:

```bash
python -m pytest -q
```

Task 8 live read-only command:

```bash
WWISE_VERSION=2024.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" WWISE_LIVE=1 python -m pytest tests/live/test_2024_live_prerequisites.py tests/live/test_2024_reflection_inventory.py tests/live/test_2024_waql_live_matrix.py -q
```

Task 10 destructive sandbox command:

```bash
WWISE_VERSION=2024.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2024.1.13.9056/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2024.1.13.9056/SampleProject/SampleProject.wproj" WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 python -m pytest tests/destructive/test_2024_project_mutation_sandbox.py tests/destructive/test_2024_soundbank_audio_sandbox.py tests/destructive/test_2024_switchcontainer_assignment_sandbox.py -q
```

Task 11 docs contract command:

```bash
python -m pytest tests/unit/test_2024_docs_contract.py -q
```

## Source Immutability

Task 10 ran through the 2024.1 destructive sandbox runtime, which asserts source SampleProject `.wproj` and `.wwu` hash and mtime invariance during cleanup. Each mutating test used a copied 2024.1 SampleProject sandbox under `WWISE_SANDBOX_ROOT`, unique WAAPI names, readback or state assertions, and cleanup or read-after-delete checks.

The destructive safety gates fail closed. Missing `WWISE_LIVE`, `WWISE_DESTRUCTIVE`, or `WWISE_VERSION` stops before sandbox preparation and before WwiseConsole launch. Active targets under `tests/_org/2024.1` or the installed SampleProject are rejected.

## Windows Caveat

Windows validation is non-blocking evidence and caveat for this 2024.1 parity packet, not a hard gate for accepting the macOS Task 8 through Task 10 evidence. macOS-generated artifacts, including any `GeneratedSoundBanks/Windows` output folder, are not Windows-host validation and must not be described as cross-platform proof.

## Known Non-Goals

- Do not claim every 2024.1 API is live-tested.
- Do not claim broad or complete 2024.1 behavioral support.
- Do not claim manifest reflection proves behavior.
- Do not claim skipped live or destructive tests are live evidence.
- Do not promote `ak.wwise.core.soundbank.getInclusions` or `ak.wwise.core.switchContainer.getAssignments` from readback-helper use.
- Do not change coverage or deferred classifications as part of this docs packet.
- Do not run live or destructive Wwise commands for Task 11.
