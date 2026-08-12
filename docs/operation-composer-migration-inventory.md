# Operation Composer migration inventory

This is the human-readable companion to
[`operation-composer-migration-inventory.json`](operation-composer-migration-inventory.json),
the machine-checked source specification for second-round migration tickets.

## Scope and invariants

The inventory covers all 34 Operation Registry entries and all 153 supported
operation/version lanes. Classification is by exact operation name, never by
native URI. `object.set`, `object.setRTPC`, and `object.createPlugin` all use
`ak.wwise.core.object.set`, but they retain separate contracts and migration
decisions.

Each exact operation/version exposes one normal input mode. A later migration
changes that lane only after its typed Adapter, semantic protocol, archive
replay, and evidence gates complete. The Agent never chooses between Composer
and Legacy JSON. Explicit Legacy commands remain compatibility-only.

## Exact operation inventory

Versions and request fields below are copied from the current Registry for
planning; the Registry remains authoritative during implementation.

| Exact operation | Versions | Current input | Closed request shape | Primary risk | Assignment |
| --- | --- | --- | --- | --- | --- |
| `audio.import` | 2021.1–2025.1 | Composer | imports; optional defaults/mode/source-control | nested rows, files, metadata, side effects | wave 00 complete |
| `audio.importTabDelimited` | 2021.1–2025.1 | Legacy | file, location, language; optional mode/source-control | caller-owned serialized file | exception candidate |
| `debug.restartWaapiServers` | 2023.1–2025.1 | Legacy | acknowledgement | expected connection loss | exception candidate |
| `debug.setAsserts` | 2021.1–2025.1 | Legacy | boolean enable | process-wide ref-count state | exception candidate |
| `debug.setAutomationMode` | 2021.1–2025.1 | Legacy | boolean enable | process-wide host mode | exception candidate |
| `debug.testAssert` | 2021.1–2025.1 | Legacy | acknowledgement | deliberate assertion | exception candidate |
| `debug.testCrash` | 2021.1–2025.1 | Legacy | acknowledgement | deliberate termination | exception candidate |
| `lua.executeCliFile` | 2023.1–2025.1 | Legacy | source file/root/authority; optional args/watchdog | exact user code and isolated I/O | exception candidate |
| `lua.executeCoreFile` | 2023.1–2025.1 | Legacy | source file/root/authority; optional args | exact user code in Authoring | exception candidate |
| `lua.executeCoreInline` | 2025.1 | Legacy | source text/root/authority; optional args | Agent composition forbidden | exception candidate |
| `object.copy` | 2021.1–2025.1 | Legacy boundary | object and parent | no implemented public verifier | non-model-facing exclusion |
| `object.create` | 2021.1–2025.1 | Legacy | parent/type/name; recursive options | recursive bounds and replace ownership | wave 02 |
| `object.createPlugin` | 2022.1–2025.1 | Legacy | target and exact class | versioned topology on shared URI | wave 02 |
| `object.delete` | 2021.1–2025.1 | Legacy | object; optional checkout | protected object and GUID absence | wave 02 |
| `object.move` | 2021.1–2025.1 | Legacy boundary | object and parent | no implemented public verifier | non-model-facing exclusion |
| `object.set` | 2022.1–2025.1 | Composer | ordered bounded object batch | recursive mixed fields/references | wave 00 complete |
| `object.setLinked` | 2023.1–2025.1 | Inline typed | object/property/platform/link state | dedicated link semantics | wave 01 complete |
| `object.setName` | 2021.1–2025.1 | Inline typed | object and name | same-GUID path transition | wave 01 complete |
| `object.setNotes` | 2021.1–2025.1 | Inline typed | object and exact text | empty text versus omission | wave 01 complete |
| `object.setProperty` | 2021.1–2025.1 | Inline typed | object/property/value/platform | live metadata and typed readback | wave 01 complete |
| `object.setRTPC` | 2022.1–2025.1 | Legacy | object/property/control input/points | dedicated curve on shared URI | wave 02 |
| `object.setReference` | 2021.1–2025.1 | Inline typed | object/reference/nullable target/platform | metadata and exact null clearing | wave 01 complete |
| `soundbank.convertExternalSources` | 2022.1–2025.1 | Legacy | sources and I/O root | proven files and isolated artifacts | wave 04 |
| `soundbank.generate` | 2021.1–2025.1 | Legacy | banks/platforms/languages/output root | host paths and artifacts | wave 04 |
| `soundbank.processDefinitionFiles` | 2022.1–2025.1 | Legacy | definition files and I/O root | derived identities/inclusions | wave 04 |
| `soundbank.setInclusions` | 2021.1–2025.1 | Legacy | bank/mode/inclusions | list pre-state/replacement | wave 04 |
| `switchContainer.addAssignment` | 2021.1–2025.1 | Legacy | container/child/state-or-switch | three identities and pair readback | wave 03 |
| `switchContainer.removeAssignment` | 2021.1–2025.1 | Legacy | container/child/state-or-switch | existing-pair and absence readback | wave 03 |
| `ui.captureScreen` | 2021.1–2025.1 | Legacy | optional view/channel/rectangle | Authoring and output confinement | wave 05 |
| `ui.commands.execute` | 2021.1–2025.1 | Legacy | command; optional targets/values/files | fresh command inventory | wave 05 |
| `ui.commands.register` | 2021.1–2025.1 | Legacy | descriptors; optional authority | ownership and registration readback | wave 05 |
| `ui.commands.unregister` | 2021.1–2025.1 | Legacy | descriptors or acknowledged IDs | ownership cannot be inferred | wave 05 |
| `waapi.call` | 2021.1–2025.1 | Legacy | manifest API; optional args/options/root | heterogeneous compatibility | exception candidate |
| `waapi.undoGroup` | 2021.1–2025.1 | Legacy | name and ordered calls | nested routes and cancellation journal | wave 06 |

## Migration order

Waves 00 and 01 are complete: the two complex Draft Adapters and five concise
single-object operations prove both typed mutation construction shapes. Planned
waves cover object graph/plug-in/delete/RTPC work, Switch Container assignments,
SoundBank and isolated-file workflows, Authoring-only UI operations, and the
compound Undo Group after relevant child contracts stabilize.

Each operation owns its action vocabulary and verifier. A wave reuses deep
Draft, canonical parsing, and Preview modules without inventing a generic
business schema.

Tab-delimited import, user-authored Lua, debug/host controls, and guarded
generic `waapi.call` are exception candidates requiring later retain-or-migrate
decisions. Unimplemented `object.copy` and `object.move` are excluded until a
separate public-operation proposal supplies safety and verification contracts.

## Legacy exit decision

This inventory does not remove or pre-authorize removal of Legacy JSON. A later
decision must show that every Registry lane is migrated or approved as an
exception; all normal Agent surfaces still expose one input; real repository,
external, and archive consumers are inventoried; history remains replayable;
and one frozen Skill/harness has complete public integration evidence on both
macOS and native Windows. Only an explicit `remove` decision may create a
separate deletion ticket.

Failed, skipped, cumulative, or cross-candidate semantic roots remain reported
as such and do not satisfy that final release gate.

## Second-round ticket slicing

Ticket one reviewed wave at a time. Each wave covers its Registry-derived
Adapter, Broker/provenance and archive adoption, exact-name input-mode cutover,
program/non-live gates, and matching real-host evidence. Do not predefine a
large generic action language or split field-level tickets before reviewing the
operation-specific vocabulary.
