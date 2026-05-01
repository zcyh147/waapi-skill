# Wwise 2023.1 parity review packet

Use this packet for Task 8 review of the 2023.1 parity evidence. The 2023.1 inventory and parity classification reconcile to 181 APIs, but behavior evidence is intentionally narrower: one live read-only URI and ten sandbox-mutating URIs have explicit 2023.1 evidence. Manifest reflection proves inventory only. Manifest reflection, skipped live tests, and skipped destructive tests are not behavioral proof.

## Promoted Evidence

Promoted live read-only evidence is limited to:

- `ak.wwise.core.object.get`, promoted to `live-tested` from the Task 3 read-only WAQL/live matrix evidence.

Promoted copied-sandbox mutation evidence is limited to these ten URIs from Task 4:

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

Task 4 readback helpers, including `ak.wwise.core.soundbank.getInclusions` and `ak.wwise.core.switchContainer.getAssignments`, can appear in evidence but remain unpromoted. They are support checks, not promoted behavior entries.

## Deferred/Excluded

Task 5 keeps 92 risky-family entries excluded. risky-family accidental promotions are zero for `soundengine`, `core.profiler`, `core.transport`, `ui`, `cli`, `core.remote`, and `debug` families.

Deferred, excluded, wrapper-only, evidence-only, untested, and conformance-only entries remain governed by the 2023.1 coverage and deferred resources. Do not promote them from manifest reflection, skipped live tests, skipped destructive tests, or helper-only readbacks.

## Commands Run

Task 3 live read-only command:

```bash
WWISE_VERSION=2023.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" WWISE_LIVE=1 python -m pytest tests/live/test_2023_live_prerequisites.py tests/live/test_2023_reflection_inventory.py tests/live/test_2023_waql_live_matrix.py -q
```

Result: exit code 0, `10 passed in 9.36s`.

Task 4 destructive sandbox command:

```bash
WWISE_VERSION=2023.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 python -m pytest tests/destructive/test_2023_project_mutation_sandbox.py tests/destructive/test_2023_soundbank_audio_sandbox.py tests/destructive/test_2023_switchcontainer_assignment_sandbox.py -q
```

Result: exit code 0, `5 passed in 97.85s`.

Task 7 audit parity command:

```bash
python -m pytest tests/unit/test_2023_cross_version_audit.py tests/unit/test_2023_docs_contract.py tests/unit/test_2023_live_coverage_matrix.py -q
```

Result: `12 passed in 0.11s`.

Task 10 final unit audit command:

```bash
python -m pytest tests/unit/test_2023_api_resource_coverage.py tests/unit/test_2023_live_coverage_matrix.py tests/unit/test_2023_deferred_registry.py tests/unit/test_2023_cross_version_audit.py tests/unit/test_2023_docs_contract.py -q
```

Result: exit code 0, `20 passed in 0.10s`.

Task 10 exact live 2023.1 command:

```bash
WWISE_VERSION=2023.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" WWISE_LIVE=1 python -m pytest tests/live/test_2023_live_prerequisites.py tests/live/test_2023_reflection_inventory.py tests/live/test_2023_waql_live_matrix.py -q
```

Result: exit code 0, `10 passed in 51.54s`.

Task 10 exact destructive 2023.1 command:

```bash
WWISE_VERSION=2023.1 WWISE_CONSOLE="/Applications/Audiokinetic/Wwise2023.1.19.8928/Wwise.app/Contents/Tools/WwiseConsole.sh" WWISE_SAMPLE_PROJECT_PATH="/Applications/Audiokinetic/SampleProject2023.1.19.8928/SampleProject/SampleProject.wproj" WWISE_SANDBOX_ROOT=.sisyphus/runtime/wwise-waapi-sandboxes WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 python -m pytest tests/destructive/test_2023_project_mutation_sandbox.py tests/destructive/test_2023_soundbank_audio_sandbox.py tests/destructive/test_2023_switchcontainer_assignment_sandbox.py -q
```

Result: exit code 0, `5 passed in 128.14s (0:02:08)`.

Task 10 default suite command:

```bash
python -m pytest -q
```

Result: exit code 0, `486 passed, 29 skipped in 1.36s`.

Task 10 final reconciliation counts: 181 reflected APIs, 181 coverage entries, 181 live matrix entries, 181 phase2 summary entries, 181 unique policy assignments, 135 deferred registry entries, 11 promoted APIs total, and 92 risky-family entries still excluded. Final status counts are `excluded=92`, `deferred=43`, `sandbox-mutating-tested=10`, `supported=16`, `untested=19`, `live-tested=1`, and `evidence-only=0`; final parity bucket counts are `excluded=80`, `deferred=62`, `sandbox-mutating-tested=10`, `conformance-only=16`, `live-tested=1`, `wrapper-only=12`, `evidence-only=0`, and `fake-route-tested=0`.

## Source Immutability

Task 4 ran through `Destructive2023SandboxRuntime`, which asserts source SampleProject `.wproj` and `.wwu` hash and mtime invariance during cleanup. Each mutating test used a copied 2023.1 SampleProject sandbox under `WWISE_SANDBOX_ROOT`, unique WAAPI names, readback or state assertions, and cleanup or read-after-delete checks. After rerun, `.sisyphus/runtime/wwise-waapi-sandboxes` retained only `.wwise-live-sandbox.lock` and no sample-project sandbox directory.

Task 6 locks the destructive safety gate fail-closed. Missing `WWISE_LIVE`, `WWISE_DESTRUCTIVE`, or `WWISE_VERSION` fails before sandbox preparation and before WwiseConsole launch. Active targets under `tests/_org/2023.1` or the installed SampleProject are rejected.

## Windows Caveat

Windows validation is non-blocking evidence and caveat for this 2023.1 parity packet, not a hard gate for accepting the macOS Task 3 through Task 7 evidence. macOS-generated artifacts, including any `GeneratedSoundBanks/Windows` output folder, are not Windows-host validation and must not be described as cross-platform proof.

## Known Non-Goals

- Do not claim every 2023.1 API is live-tested.
- Do not claim full or complete 2023.1 behavioral support.
- Do not claim manifest reflection proves behavior.
- Do not claim skipped live or destructive tests are live evidence.
- Do not change coverage or deferred classifications as part of this docs packet.
- Do not run live or destructive Wwise commands for Task 8.
