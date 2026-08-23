# ADR 0003: Gateway compiles business declarations

- Status: Accepted
- Date: 2026-08-24
- Scope: deep model-facing interfaces for complex named mutations
- Refines: ADR 0001 and ADR 0002

## Context

The first Operation Composer removed caller-authored request JSON but left the
Agent responsible for exact Wwise types, complete mutation paths, metadata
scopes, action order, batch boundaries, and partial shell serialization. Fresh
Agent failures repeatedly reproduced those leaked implementation details even
though the Gateway already knew how to validate or derive them.

## Decision

The Agent owns natural language to closed, high-level Business Declarations;
the Gateway owns Business Declarations to the exact versioned WAAPI execution
plan. The first reference interface is `audio.import`: it accepts one or more
semantic import declarations, identifies new targets by parent handle plus name
and kind and existing targets by object handle, discovers long-tail fields live,
constructs paths and wire types, orders and expands native rows, and produces
one immutable Change Preview. The public operation remains `audio.import`;
`ImportPlan` is internal compiler language rather than another user-facing
concept.

Common fields use stable names and explicit units. Dynamic fields use bounded
Field Handles bound to the current task, project, Wwise build, object/class
scope, and metadata snapshot. Exact Wwise property tokens, mutation paths,
metadata scopes, native modes, ordering, batching, revision arithmetic, and
shell quoting are not model inputs. User-explicit create, re-import, or replace
intent wins; otherwise the Gateway derives the only mode consistent with the
declared target and live state and fails closed when more than one meaning
remains.

Preview uses readable Wwise terminology in `field: value` form and hides native
requests, GUIDs, digests, and handles unless detail is requested. Revising a
batch invalidates its Preview and creates a new one. Composition state is useful
only in the current task; no cross-conversation resume interface is added.

Live Authoring metadata is the normal extension mechanism for plug-in and
custom properties. A reflection gap requires a separately developed trusted
Adapter; a value that cannot be verified is not exposed. The Gateway keeps
explicit byte, result, and time budgets, but does not present an arbitrary row
ceiling as a Wwise `audio.import` limitation.

The former low-level `audio.import` Composer remains only while the new Adapter
is incomplete. Cutover requires generated full-field parity, five-version
program equivalence, negative and stale-handle coverage, integration-intent
coverage, and focused evidence for type mapping, path construction,
ordering/batching, and continuation copying. Once those gates pass, the old
implementation and tests are deleted in the same change; they do not remain as
a fallback.

## Consequences

- The model chooses business meaning but cannot improvise Wwise serialization.
- One native `audio.import` request may contain many logical imports; the
  Gateway compiler, not the Agent, owns its row layout.
- New semantic Adapters require stronger up-front modeling and generated parity
  evidence, but remove repeated prompt repair from the runtime path.
- This decision establishes the seam for later complex operations without
  requiring every operation to share the import vocabulary.
