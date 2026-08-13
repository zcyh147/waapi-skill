# ADR 0001: Gateway-owned composition for complex mutations

- Status: Superseded in part by ADR 0002
- Date: 2026-08-11
- Scope: model-facing complex named mutations

## Context

ADR 0002 supersedes this record's decision to retain a model-facing Legacy JSON
Adapter and its compatibility commands. The Composer lifecycle, canonical
request representation, immutable Preview, and business-orchestration boundary
remain in force.

The packaged mutation layer already validates closed, versioned operation
requests and compiles them into native WAAPI payloads behind immutable Preview,
authorization, execute-once, and verification boundaries. However, the former
normal input required the Agent to serialize an entire nested
`operation-request JSON` into one shell argument. Repeated failures in a
multi-target `object.set` request showed that strict fail-closed parsing
preserved safety but produced avoidable completion and user-experience failures.

`object.set` and `audio.import` provide two different structures with enough
program and real-host evidence to establish a common input lifecycle without
pretending their business rows are identical.

## Decision

Business Orchestration supplies intent to the Operation Composer, which records
an Operation Draft and materializes a Canonical OperationRequest. The Legacy
JSON Adapter remains a compatibility input to the same Change Preview pipeline.

For complex operations migrated to `input_mode=composer`, the Agent supplies
small operation-specific typed actions and Gateway-generated handles. The
Gateway deterministically serializes them into the existing Canonical
OperationRequest. It does not decide the user's business intent.

The public normal lifecycle is:

1. start an empty, version-bound Operation Draft;
2. apply typed actions with revision compare-and-swap;
3. inspect or perform one bounded live check;
4. create one immutable Change Preview from the checked revision;
5. follow the existing confirmation or policy-authorization, execute-once, and
   verification lifecycle; or cancel before Preview.

The Operation Registry is authoritative for each `(operation, version)` input
mode and for fields, types, versions, and limits. A Composer lane must have one
real local Adapter; a Legacy lane cannot start a new Operation Draft. Normal
discovery presents only the declared input mode. The Legacy JSON Adapter
remains available only through explicit compatibility commands and shares the
same canonical parser and Preview ingress.

Mutable Operation Draft state and immutable transaction Preview state remain in
separate stores. The crash-safe handoff binds one Draft revision to at most one
transaction identifier. Composer check evidence is diagnostic and is repeated
authoritatively during Preview preparation.

Normal user-facing prose describes objects, requested changes, outcomes, risks,
and whether anything changed. It does not expose API names, operation names,
Drafts, transactions, identifiers, hashes, capabilities, states, or commands.

## Consequences

- JSON punctuation and canonical serialization are no longer an Agent concern
  for migrated complex operations.
- Business planning remains with the Agent; no planner model is embedded in the
  Gateway.
- Common lifecycle, status, limits, and errors can evolve in one deep Module,
  while operation-specific action vocabulary remains local.
- Every new migrated operation needs a complete typed Adapter and Registry lane
  declaration before normal cutover.
- Existing Legacy consumers continue through an explicit compatibility surface;
  removal requires separate consumer evidence and a later decision.
- More commands may be used during composition, but each is short, bounded,
  auditable, and atomically revision-bound.

## Rejected alternatives

### Accept occasional malformed JSON because it fails closed

Rejected. It preserves safety but makes expected complex work fail before the
reviewed operation contract is reached and produces a poor user experience.

### Repair malformed JSON or retry automatically

Rejected. Guessing punctuation or values weakens fail-closed behavior and can
change user intent.

### Add large operation-specific flag surfaces

Rejected as the primary architecture. Flat shortcuts may be useful, but nested
batch flags duplicate Registry schemas and do not provide a uniform lifecycle.

### Put a planner or another language model inside the Gateway

Rejected. The Agent already performs Business Orchestration; duplicating that
reasoning would add cost, ambiguity, and a second source of intent.

### Replace the canonical request and Preview pipeline

Rejected. The existing strict parser, preparation, guards, authorization,
dispatch, verification, and cleanup remain the safety authority and are reused
unchanged downstream of composition.
