# Runtime control verification decisions (#186)

Decision date: 2026-10-24. This records the existing spec's distinction between
native acknowledgement and independently observed effect. It neither excludes
operations nor converts failed evidence to PASS. Exact branch bindings and
required program/native receipts remain necessary for ticket acceptance.

## Standalone controls and workflow observations

| Control / versions | Supported standalone proof | Why the available observation is different |
| --- | --- | --- |
| `enableProfilerData`, 2021–2025 | Accepted ordered directives and native result schema; enabled-state, empty-list effect, repetition precedence and restoration remain unclaimed. | Dataset readers return captured data, not the current enablement map. Neither empty nor nonempty data establishes the final settings. |
| `startCapture` / `stopCapture`, 2021–2025 | Native result and returned capture time; execute-once paired stop and owned-host cleanup. | `getCursorTime(capture)` is the latest capture time, not a running flag. Stable times do not prove stopped without a progress guarantee. `profiler.stateChanged` reports GameSync StateGroup/State, not capture state. |
| `registerMeter` / `unregisterMeter`, 2024–2025 | Native result and balanced cleanup; registration membership is not independently verified. | `getMeters` is the documented data observer and the owned flows prove attributable meter data. Its requested capture time can refer to retained/pre-existing data; it does not establish current membership, reference counts or unregister timing. |
| `transport.prepare`, 2022–2025 | Acknowledged preparation of the bound object. | Transport state is playback state. LoadedMedia describes SDK preparation and is not a documented postcondition of this Authoring command. Capture-log Prepare activity has no established attributable completion field for this call. |
| `transport.useOriginals`, 2023–2025 | Accepted Original/Converted selection; actual global mode/restoration unverified. | File paths describe available assets. Playback state, voice/streaming data and the reflected state Topics do not establish this toggle. |
| Console `log.clear`, 2023–2025 | Acknowledged channel clear; disappearance of prior entries unverified. | The matching SDK documents empty Console `log.get` results. `log.itemAdded` observes additions, not removals or clear completion. Silence cannot establish clearing. |

These are truthful result-schema boundaries for the current standalone
contracts. A conditional read of already available meter/capture data may
establish that data fact; it must not be relabeled current registration or
capture-running proof. Do not start capture, add indefinite polling or demand
acoustic output merely to strengthen an unrelated control's verifier.

The concrete alternative needed for stronger state claims would be a native
field/event with documented current-setting, lifecycle, registration or mode
semantics. A missing Skill verifier is not excused when such an observer exists.
The reviewed interfaces above do not establish those stronger relationships.
No universal prior-state restoration or waveform requirement is added here.

## Suitable observers and remaining evidence

- Console `log.addItem` has a suitable `log.itemAdded` observer, already used by
  the Gateway around its single dispatch. The retained 2025 event proves that
  exact effect. The 2023/2024 bounded waits received no event; they remain
  unresolved observations, not native absence or an inherent Console limit.
  An unchanged retry is not the next step without a distinct source-backed
  diagnosis. Authoring getter-based add/clear facts remain separate.
- The 2025 `moveCursor` returned time has a suitable independent user-cursor
  getter. Four move alternatives still need their selected native facts;
  existing setter, meter and other reader observations do not need repetition.
- Nonempty LoadedMedia remains an independent read obligation on 2023–2025.
  R106's complete empty Event-preparation result does not establish native
  absence, SDK equivalence or that this read is unsupported.

## Authoritative sources and accounting

Use matching `skills/waapi-skill/resources/native-catalog/<version>/`
`wwise-authoring.json` and `wwise-console.json`, including exact function and
Topic schemas. Meter functions are present in 2024/2025; the reflected
`profiler.stateChanged` payload in 2022–2025 contains `stateGroup` and `state`.
The 2024 meter default is Master Audio Bus; 2025 names Main Audio Bus.

Public meanings and limits live in
`runtime_inspection_business_contracts.py` (including
`PROFILER_CAPTURE_DATA_VERIFICATION` and `CONSOLE_LOG_ADD_OBSERVER`).
`operation_registry.py` selects the result-schema or operation-local verifier.
`runtime_log_effects.py` and `runtime_log_observer.py` own getter/Topic-based
log proof; `transaction_cleanup.py` and `execution_contracts.py` retain paired
cleanup. These are implementation sources, not standalone execution evidence.

[The test inventory](../../../tests/TEST_INVENTORY.md) records native candidates,
original outcomes and reuse limits. Keep acknowledged command inputs,
independently observed data/effects, and historical automated verdicts separate
when publishing exact branch evidence. In particular, no source-only decision
here grants native coverage or repairs a BLOCKED lifecycle record.
