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

Each exact operation/version exposes one normal typed input mode. The Agent
never chooses between typed construction and a caller-authored canonical
document. Canonical JSON remains only an internal materialization and frozen
archive representation, never a packaged product ingress.

## Exact operation inventory

Versions and request fields below are copied from the current Registry for
planning; the Registry remains authoritative during implementation.

| Exact operation | Versions | Current input | Closed request shape | Primary risk | Assignment |
| --- | --- | --- | --- | --- | --- |
| `audio.import` | 2021.1–2025.1 | Business declaration | bound objects, semantic kinds, stable fields, custom Field Handles | Gateway-derived rows, paths, types, metadata scopes, side effects | deep cutover complete |
| `audio.importTabDelimited` | 2021.1–2025.1 | Inline typed | file, location, language; optional mode/source-control | caller-owned serialized file | wave 05 file/Lua complete |
| `debug.restartWaapiServers` | 2023.1–2025.1 | Inline typed (zero value) | Gateway-owned acknowledgement | expected connection loss | wave 05 debug complete |
| `debug.setAsserts` | 2021.1–2025.1 | Inline typed | boolean enable | process-wide ref-count state | wave 05 debug complete |
| `debug.setAutomationMode` | 2021.1–2025.1 | Inline typed | boolean enable | process-wide host mode | wave 05 debug complete |
| `debug.testAssert` | 2021.1–2025.1 | Inline typed (zero value) | Gateway-owned acknowledgement | deliberate assertion | wave 05 debug complete |
| `debug.testCrash` | 2021.1–2025.1 | Inline typed (zero value) | Gateway-owned acknowledgement | deliberate termination | wave 05 debug complete |
| `lua.executeCliFile` | 2023.1–2025.1 | Composer | source file/root/authority; optional typed args/watchdog | exact user code and isolated I/O | wave 05 file/Lua complete |
| `lua.executeCoreFile` | 2023.1–2025.1 | Composer | source file/root/authority; optional typed args | exact user code in Authoring | wave 05 file/Lua complete |
| `lua.executeCoreInline` | 2025.1 | Composer | source text/root/authority; optional typed args | Agent composition forbidden | wave 05 file/Lua complete |
| `object.copy` | 2021.1–2025.1 | Inline typed | object and parent | returned GUID and parent/path verification | wave 02 object lifecycle complete |
| `object.create` | 2021.1–2025.1 | Composer | parent/type/name; recursive options | recursive bounds and replace ownership | wave 02 object lifecycle complete |
| `object.createPlugin` | 2022.1–2025.1 | Composer | target and exact class | versioned topology on shared URI | wave 02 complete |
| `object.delete` | 2021.1–2025.1 | Inline typed | object; optional checkout | protected object and GUID absence | wave 02 object lifecycle complete |
| `object.move` | 2021.1–2025.1 | Inline typed | object and parent | stable GUID and parent/path verification | wave 02 object lifecycle complete |
| `object.set` | 2022.1–2025.1 | Composer | ordered bounded object batch | recursive mixed fields/references | wave 00 complete |
| `object.setLinked` | 2023.1–2025.1 | Inline typed | object/property/platform/link state | dedicated link semantics | wave 01 complete |
| `object.setName` | 2021.1–2025.1 | Inline typed | object and name | same-GUID path transition | wave 01 complete |
| `object.setNotes` | 2021.1–2025.1 | Inline typed | object and exact text | empty text versus omission | wave 01 complete |
| `object.setProperty` | 2021.1–2025.1 | Inline typed | object/property/value/platform | live metadata and typed readback | wave 01 complete |
| `object.setRTPC` | 2022.1–2025.1 | Composer | object/property/control input/points | dedicated curve on shared URI | wave 02 complete |
| `object.setReference` | 2021.1–2025.1 | Inline typed | object/reference/nullable target/platform | metadata and exact null clearing | wave 01 complete |
| `soundbank.convertExternalSources` | 2022.1–2025.1 | Composer | sources and I/O root | proven files and isolated artifacts | wave 04 complete |
| `soundbank.generate` | 2021.1–2025.1 | Composer | banks/platforms/languages/output root | host paths and artifacts | wave 04 complete |
| `soundbank.processDefinitionFiles` | 2022.1–2025.1 | Inline typed | definition files and I/O root | derived identities/inclusions | wave 04 complete |
| `soundbank.setInclusions` | 2021.1–2025.1 | Composer | bank/mode/inclusions | list pre-state/replacement | wave 04 complete |
| `switchContainer.addAssignment` | 2021.1–2025.1 | Inline typed | container/child/state-or-switch | three identities and pair readback | wave 03 complete |
| `switchContainer.removeAssignment` | 2021.1–2025.1 | Inline typed | container/child/state-or-switch | existing-pair and absence readback | wave 03 complete |
| `ui.captureScreen` | 2021.1–2025.1 | Inline typed | optional view/channel/rectangle | Authoring and output confinement | wave 05 complete |
| `ui.commands.execute` | 2021.1–2025.1 | Inline typed | command; optional targets/values/files | fresh command inventory | wave 05 complete |
| `ui.commands.register` | 2021.1–2025.1 | Composer | descriptors; optional authority | ownership and registration readback | wave 05 complete |
| `ui.commands.unregister` | 2021.1–2025.1 | Composer | descriptors or acknowledged IDs | ownership cannot be inferred | wave 05 complete |
| `waapi.call` | 2021.1–2025.1 | Internal canonical | Gateway-materialized exact URI request | heterogeneous internal transaction representation | not model-facing |
| `waapi.undoGroup` | 2021.1–2025.1 | Composer | name and ordered typed child handles | nested routes and cancellation journal | wave 06 complete |

## Migration order

Waves 00 through 06 are complete: complex Draft Adapters and concise typed operations
cover object batches, imports, single-object edits, recursive creation, object
lifecycle, plug-in topology, RTPC curves, Switch Container assignments, and
SoundBank/isolated-file workflows, Authoring-only UI operations, caller-owned table
imports, exact user-authored Lua with bounded typed argument maps, and compound Undo
Groups whose ordered children are disclosed from their exact typed contracts.

Each operation owns its action vocabulary and verifier. A wave reuses deep
Draft, canonical parsing, and Preview modules without inventing a generic
business schema.

Debug/host controls use their closed typed operations. Generic `waapi.call` is
an internal canonical transaction representation produced only after an exact
typed request has been validated and materialized. `object.copy` and
`object.move` have closed typed inputs and operation-specific identity, parent,
and path verification.

## Single typed input decision

ADR 0002 completed the product cutover: every normal model-facing lane uses
Gateway-owned typed construction, while historical JSON and action grammars
exist only in versioned offline replay codecs. Pre-cutover pending Drafts and
Previews fail with a bounded recreate instruction instead of executing through
compatibility code.

Failed, skipped, cumulative, or cross-candidate semantic roots remain reported
as such and do not satisfy that final release gate.

## Second-round ticket slicing

Ticket one reviewed wave at a time. Each wave covers its Registry-derived
Adapter, Broker/provenance and archive adoption, exact-name input-mode cutover,
program/non-live gates, and matching real-host evidence. Do not predefine a
large generic action language or split field-level tickets before reviewing the
operation-specific vocabulary.
