# Deep `audio.import` business interface

## Status

Accepted design for implementation. This document defines the first deep
business interface over the existing immutable Preview, authorization,
execute-at-most-once, verification, and cleanup pipeline.

## Problem

The current Composer rejects malformed requests safely, but still asks the
Agent to know and serialize implementation facts that the Gateway can derive:

1. `Sound SFX` is an import wire type while `Sound` is the related live query
   and metadata scope.
2. New Wwise descendants require exact typed path segments and backslash
   serialization.
3. Structure and media rows require a particular dependency order and may
   expand one logical import into multiple native rows.
4. Composition exposes partial command continuations and more than one command
   representation.

Those are compiler responsibilities, not user intent. Repeating them in Skill
prose or campaign prompts does not deepen the interface.

## Ownership boundary

The Agent converts natural language into closed Business Declarations. A
declaration contains the object or parent chosen from Gateway evidence, the
requested authoring outcome, and explicit business values.

The Gateway converts those declarations into the exact WAAPI plan. It owns:

- Wwise-version and live-host selection;
- stable business kind to metadata type, native object type, and verifier type;
- parent/child compatibility and complete Wwise path construction;
- live property/reference discovery and Field Handles;
- default expansion, dependency ordering, and native row expansion;
- request size/resource validation and one complete continuation;
- immutable Preview, authorization, dispatch, verification, and cleanup.

No LLM runs inside the Gateway. Deterministic compilation is possible because
the Agent's input is already closed: target, requested state, values, and
explicitly requested mode are present before compilation.

## Public operation

The public business operation remains `audio.import`. It accepts one or more
complete import declarations and produces one Change Preview. The interface
does not expose a separate `ImportPlan` concept merely because execution has not
yet occurred.

An implementation may persist declarations across short Gateway calls so the
Agent does not serialize one large shell argument. That mutable storage is an
Operation Draft bound to the current task. Its public vocabulary describes
import business nouns rather than low-level actions; its internal compilation
artifact may be named `ImportPlan`.

### Target forms

- **New target:** exact parent handle, child name, and stable business kind.
  Gateway constructs the full Wwise path and all native type representations.
- **Existing target:** exact object handle and new media or requested fields.
  Gateway preserves and verifies the existing GUID.
- **Explicit replacement:** exact existing object handle plus an explicit user
  request to replace. Replacement is never inferred from a collision.

If the user explicitly requests create, re-import, or replace, that choice is
preserved. Otherwise the Gateway derives the only mode consistent with target
form and live state. Ambiguity returns structured repair instead of a guess.

### Values

- Common fields have stable semantic names and explicit units, for example
  `volume_db`, `fade_time_ms`, `delay_ms`, `max_instances`, and
  `loop=infinite`.
- Omission means do not set or override. A value is derived only when it is a
  necessary consequence of an explicit business declaration.
- Batch-wide user intent is represented once and expanded by the Gateway;
  repeated row values without batch-wide intent remain row-local.
- Long-tail properties and references use live-discovered Field Handles plus a
  business scalar or exact target handle.
- Provably equivalent spellings and units may be normalized. Ambiguous enums,
  invalid objects, disabled fields, and out-of-range values are rejected with
  candidates or the valid range; values are never silently clamped.

### Plug-in and custom fields

For a registered Authoring property/reference, the Gateway enumerates the exact
object or class scope with `getPropertyAndReferenceNames`, obtains metadata with
`getPropertyInfo`, checks `isPropertyEnabled` when current dependency/platform
state matters, issues a bound Field Handle, and reads the field back after
mutation.

Runtime-only, opaque, private-UI, or proprietary values are not assumed to be
discoverable. A proven reflection gap requires a separately implemented and
reviewed Adapter. If the value cannot be verified, the public Skill reports a
capability boundary rather than exposing a raw escape hatch.

## Compiler pipeline

1. Validate each Business Declaration atomically. Incomplete or invalid input
   leaves the current Draft byte-for-byte unchanged.
2. Resolve object/parent identities and bind live project, Wwise version/build,
   and task authority.
3. Resolve stable business kinds and discover every requested dynamic field.
4. Expand explicit batch settings into logical rows without losing row-local
   overrides.
5. Build canonical paths and the logical object/media graph.
6. Topologically order structure, media, Event, and Switch-assignment effects.
7. Materialize the complete native `audio.import` arguments and expected
   post-state. One logical item may expand to multiple native rows.
8. Enforce explicit request-byte, result, file, and time budgets. There is no
   model-facing arbitrary import-row limit presented as a Wwise limitation.
9. Return either structured repair or one immutable Change Preview.
10. After authorization, dispatch at most once and verify the exact requested
    business state.

## Repair contract

A failed declaration returns a stable machine repair object and a concise
business explanation. It identifies the rejected field, preserves the Draft
revision, and supplies only information that can safely repair the declaration:
valid range, exact enum choices, candidate objects, missing required facts, or
a stale/scope mismatch. It never manufactures a replacement value or repairs a
native request string.

## Preview

The default Preview is organized by business object and uses readable Wwise
terminology with one `field: value` per line, localized to the conversation
where appropriate. Example:

```text
对象：Rain_Bed
类型：Sound SFX
循环方式：Infinite
音量：-4 dB
输出总线：Weather_Bus
```

Native WAAPI arguments, GUIDs, digests, handles, and shell envelopes appear only
in an explicit detail/audit view. Revising any declaration invalidates the old
Preview while preserving it as audit evidence; the revised batch receives a
new Preview and authorization decision.

## Lifetime

Mutable composition is limited to the current Agent task/conversation and its
task authority. It may span messages needed to reach Preview and confirmation,
but the product exposes no cross-conversation list, search, or resume feature.
If task authority is lost, the Draft expires or is abandoned and must be
recreated from user intent.

## Lossless cutover contract

The old `audio.import` Composer cannot be removed until all of its permitted
capabilities are either:

- a stable semantic business field;
- deterministically derived by the Gateway;
- represented by a live-bound dynamic Field Handle; or
- represented by a separately reviewed closed Adapter.

The cutover gate is:

1. Generate a machine-readable mapping for every old request option, default,
   row field, nested field, enum, version delta, and safety restriction.
2. Prove five-version semantic-to-canonical equivalence with focused positive,
   negative, stale-handle, scope, type, range, omission, and repair tests.
3. Cover the Weather, Rifle, Footsteps, and Weapons import behaviors plus
   paraphrased high-level intents without raw Wwise types, tokens, full mutation
   paths, action ordering, batching, revision arithmetic, or shell quoting.
4. Prove the four historical failure families directly: type mapping, path
   construction, ordering/batching, and unique complete continuation copying.
5. Pass focused tests, Program, and Non-live before real Wwise or Fresh Agent
   campaigns.
6. Remove the old model-facing implementation, references, and tests in the
   same cutover change. Historical evidence remains replayable from frozen
   commits; no production fallback remains.

Only after this gate does public integration acceptance resume on macOS and
native Windows.
