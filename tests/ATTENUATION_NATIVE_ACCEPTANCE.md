# Attenuation activation acceptance — 2026-10-17

Issue #167 has focused public Gateway real-Wwise evidence on macOS for all five
supported versions. This is deterministic developer validation, not Fresh Agent
acceptance or native-Windows evidence.

## Frozen candidate and completed runs

Candidate `700a8477` was unchanged throughout these five sequential invocations
of `test_attenuation_activation_public_gateway_native` in
`tests/destructive/test_attenuation_activation_gateway.py`. Each invocation used
normal `ci/test.sh --version <version> --mode destructive` readiness, the explicit
test path, and exact `-k attenuation_activation_public_gateway_native` selection.
Each exited 0 with **1 passed, 32 deselected**.

| Version | Elapsed | Evidence root basename |
| --- | ---: | --- |
| 2021.1 | 56.00 s | `attenuation-public-700a8477-2021-r1` |
| 2022.1 | 42.61 s | `attenuation-public-700a8477-2022-r1` |
| 2023.1 | 42.37 s | `attenuation-public-700a8477-2023-r1` |
| 2024.1 | 42.41 s | `attenuation-public-700a8477-2024-r1` |
| 2025.1 | 42.46 s | `attenuation-public-700a8477-2025-r1` |

The local roots are retained under
`/Users/xiye/.codex/worktrees/waapi-dependencies/waapi-skills/.waapi-skill-state/`.
Every root contains:

- `evidence/attenuation-public.json`: public Gateway receipts, independent
  metadata, before/after readbacks, and read-only oracle call records.
- `evidence/start.json`: endpoint, private HOME, owned Wine prefix, launch
  working directory, sandbox identity, and initial full source hash.
- `evidence/lifecycle.json`: final status, source hashes and project mtimes,
  sandbox retention, and cleanup errors.

Preserve these ignored evidence roots before archiving the worktree. They are
local run evidence, not files embedded in this Git document.

## Behavior proved

The public Gateway creates an owned Attenuation, Sound, and
RandomSequenceContainer in each disposable project. On 2022.1–2025.1, one
`object.set` transaction per source associates the attenuation and enables its
missing positioning prerequisite. On 2021.1, a separately confirmed
`object.setProperty` Preview enables the prerequisite before a separately
confirmed `object.setReference` Preview. Independent exact-GUID readback checks
Attenuation, ListenerRelativeRouting, OverridePositioning, and preservation of
id/name/type/path, Volume, and notes for both source types.

The fresh native objects had ListenerRelativeRouting=true and
OverridePositioning=false. The native runs therefore prove override activation
and preservation of already-satisfied listener routing. The false-to-true
listener-routing derivation is proved by public fake-client tests across the
four atomic-operation versions, not by these native initial states.

The compact Preview includes the exact added override field and value even
when dispatch/pre-state sections use digest projections. Already-satisfied
fields are omitted from the added-change notice and native write. The final
`agent_result` insertion order is preserved.

Every final lifecycle record reports PASS, no errors, identical full source
hashes, identical source project mtimes, and `sandbox_retained=false`. The final
host process check found no Wwise.exe or WwiseConsole.exe process. Each launch
used `<root>/owned/wwise-user-home` and its matching
`Library/Application Support/Wwise2019/Bottles/Wwise2019x64` prefix rather than
the inherited user HOME.

## Earlier retained evidence

These attempts remain separate; they are not counted as final-candidate passes.
Their source hashes and project mtimes also remained unchanged.

| Root basename | Result and finding |
| --- | --- |
| `attenuation-public-77928fc4-2025-r1` | FAIL during fixture parent binding: 2025.1 canonical hierarchy is Containers. |
| `attenuation-public-c070beb3-2025-r1` | FAIL in fixture reader: compact field discovery uses `meaning_results[].candidates`. |
| `attenuation-public-e89b9ad0-2025-r1` | FAIL before association dispatch: native OverridePositioning has a terminal self-override descriptor. |
| `attenuation-public-6e4f1627-2025-r1` | PASS, 1 passed / 32 deselected, 41.91 s; superseded by the final-candidate run. |
| `attenuation-public-6e4f1627-2021-r1` | FAIL before prerequisite mutation: terminal override selection needed object-scoped handling of its false enabledness report. |

Failed sandboxes were retained/quarantined by the existing ScenarioLifecycle;
none was deleted to obtain a passing result. The repair recognizes only the
observed exact UI visibility and Boolean positioning-terminal descriptors;
unknown activation conditions, conflicting values, and ordinary dependency
cycles remain fail-closed.
