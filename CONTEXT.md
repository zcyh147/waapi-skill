# Domain Context

This repository exposes Wwise project work through a version-aware local
Gateway. The domain boundary is the user's requested audio-authoring outcome,
not a raw WAAPI payload or a shell command.

## Business Orchestration

Business Orchestration is the Agent's responsibility for turning a user's
request into ordered, meaningful authoring steps. It chooses targets, values,
and transaction boundaries from the user's intent and Gateway evidence. It does
not serialize native WAAPI requests, repair malformed JSON, or invent fields.

Example: “route these three weapons to the correct buses and lower the
mechanical layer” becomes one reviewed batch of three target corrections. The
Agent chooses those corrections; the Gateway owns their typed representation.

## Operation Composer

The Operation Composer is the Gateway-owned input interface for complex named
mutations. It accepts small, versioned typed actions, validates them against the
Operation Registry, and deterministically materializes one Canonical
OperationRequest. Common lifecycle and errors are shared; action vocabulary is
local to each operation Adapter.

`object.set` and `audio.import` are the first two structurally different
Adapters using this interface. Their common commands are start, apply, inspect,
check, preview, and cancel. Their row fields and actions are intentionally not
forced into a single generic business schema.

## Operation Draft

An Operation Draft is mutable, task-capability-bound composition state. It
records typed facts, revisions, validation evidence, and one crash-safe handoff
reservation. It has no Wwise side effect and is not permission to mutate a
project. Invalid actions are atomic: they do not advance its revision or change
its durable bytes.

The Operation Draft Store is separate from the immutable transaction store.
Draft authority does not authorize Preview confirmation or execution.

## Canonical OperationRequest

The Canonical OperationRequest is the closed, versioned mutation request parsed
by `operation_registry.py`. It is the single downstream truth for preparation,
native dispatch, project/runtime guards, verification, and cleanup. Composer
materialization must re-enter the same strict parser used by the compatibility
JSON path; it is never trusted as a pre-parsed bypass.

## Legacy JSON Adapter

The Legacy JSON Adapter accepts a complete caller-serialized
`waapi-skill.operation-request/v1` document. It remains an explicit
compatibility surface for existing consumers while operations migrate. It is
not shown as a competing normal input when an operation's Registry lane is
`composer`, and the Agent never chooses between both paths.

## Change Preview

A Change Preview is an immutable transaction artifact derived from a Canonical
OperationRequest and current live evidence. It binds project/runtime guards,
pre-state, authorization, execution-at-most-once, verification, and cleanup.
Preview creation has no mutation side effect. Confirmation or durable policy
authorization is still required before execution.

## Boundary summary

- The user describes business outcomes.
- The Agent performs Business Orchestration and supplies typed values.
- The Operation Composer serializes complex normal inputs.
- The Operation Registry owns field, type, version, and limit truth.
- The Operation Draft Store owns mutable composition state.
- The transaction store owns immutable Preview and authorization state.
- The dispatcher and verifier own native execution and business evidence.
