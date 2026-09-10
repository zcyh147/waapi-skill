# Domain Context

This repository exposes Wwise project work through a version-aware local
Gateway. The domain boundary is the user's requested audio-authoring outcome,
not a raw WAAPI payload or a shell command.

## Business Orchestration

Business Orchestration is the Agent's responsibility for turning a user's
request into closed, high-level business declarations. It chooses the requested
targets, outcomes, values, and explicit operation modes from the user's intent
and Gateway evidence. It does not choose native action order or batch
boundaries, construct Wwise paths or wire types, serialize native WAAPI
requests, repair malformed JSON, or invent fields.

Example: “route these three weapons to the correct buses and lower the
mechanical layer” becomes three closed target/value declarations. The Agent
chooses those corrections; the Gateway owns their typed representation,
dependency order, batch construction, and exact Wwise execution plan.

## Business Declaration

A Business Declaration is one closed statement of requested authoring state in
stable Wwise-facing terms. It identifies the intended object or parent, the
requested outcome, and only the values the user stated or that the outcome
necessarily implies. It contains no complete mutation path, native wire token,
shell syntax, action ordering, or batch bookkeeping.

Common fields use stable names with explicit units, such as `volume_db` and
`fade_time_ms`. Long-tail fields use live-discovered, scope-bound Field Handles
rather than caller-authored native property tokens.

## Import Batch

An Import Batch is one or more Business Declarations whose primary outcome is
Wwise audio import. It may describe new structure or media under an exact
parent, re-import media into an existing object, or explicitly replace an
existing object. The Gateway compiles the complete batch into one native
`audio.import` request whenever its resource boundary permits.

`ImportPlan` is an internal compiler artifact, not a model-facing or
user-facing domain term. Before execution, an Import Batch produces the same
Change Preview as every other mutation.

## Field Handle

A Field Handle is Gateway-issued authority for one live-discovered Wwise
property or reference in an exact object or class scope. It is bound to the
current task, project, Wwise version/build, metadata snapshot, token, type, and
restrictions. It lets the Agent provide a business value without retyping or
guessing the native field token.

## Gateway-Owned Request Construction

Gateway-Owned Request Construction is the rule for every model-facing WAAPI
function and topic input. The Agent supplies typed business values; the Gateway
deterministically materializes the exact versioned request. A complete caller-
serialized request, raw arguments, or raw options are never normal or
compatibility inputs. Existing closed query and topic interfaces satisfy this
rule without becoming mutation Drafts.

## Gateway-Owned Operation Input

Gateway-Owned Operation Input applies Gateway-Owned Request Construction to a
named mutation and deterministically materializes one Canonical
OperationRequest.

The Operation Registry selects one construction shape for each exact operation
and version. A zero-value operation needs no supplied business value; an inline
operation accepts one bounded typed submission; a draft operation uses an
Operation Draft for repeated, nested, or correctable facts. These shapes are
Gateway concerns, not choices presented to the Agent.

The exact version comes from the configured and live-attested Skill session,
not from a repeated model choice. Drafts and Previews bind that version and
fail when configuration, live Wwise, or a continuation disagrees.

## Operation Composer

The Operation Composer is the Gateway-Owned Operation Input implementation for
draft-shaped named mutations. It accepts small, versioned Business
Declarations, validates them against the Operation Registry, and
deterministically materializes one Canonical OperationRequest. Common lifecycle
and errors are shared; declaration vocabulary is local to each operation
Adapter.

`object.set` and `audio.import` are structurally different Adapters using this
interface. Their lifecycle is shared, but their business declarations are not
forced into a single generic schema. In particular, `audio.import` accepts an
Import Batch and owns the exact Wwise type mapping, path construction,
dependency ordering, native row expansion, and batching below that boundary.

## Generic Schema Composer

The Generic Schema Composer is the Gateway-Owned Operation Input implementation
for reflected executable routes without a dedicated named operation. It
compiles the exact versioned reflected argument and option schemas into typed
zero-value, inline, or draft continuations and deterministically materializes
their native request. It never exposes raw `args`, raw `options`, or complete
JSON as model inputs.

Every reflected route that the packaged execution policy permits must have a
complete typed construction path. Complex schemas require complete structural
actions and reviewed semantic mappings rather than being left unsupported.
Dedicated named operations remain preferred where they provide stronger
business terminology, safety rules, or verification.

An Open Typed Map is permitted only where the exact reflected schema explicitly
allows caller-defined keys through an open object or matching key pattern. The
Agent supplies one bounded key and typed value at a time; the Gateway enforces
the reflected key pattern, value schema, depth, node count, and byte ceilings.
It never accepts an entire caller-serialized map or JSON document.

## Full WAAPI Input Coverage

Full WAAPI Input Coverage means that every reflected function and Topic lane in
every supported Wwise version has a Gateway-Owned Request Construction contract
for its correct host. Coverage includes zero-value, inline, draft, query, Topic,
file, source-code, terminal, and generic schema-derived inputs. A lane may not
remain unavailable merely because its schema is complex or its verifier has not
yet been implemented.

Full coverage does not repeal the packaged execution policy. A route may be
supported while a dangerous native field remains intentionally blocked, such as
an external-command hook, an unrestricted module or file loader, or a raw native
property escape hatch. The typed contract exposes every permitted shape and
returns the existing explicit safety boundary for prohibited shapes.

A host mismatch is not a missing lane. An Authoring-only, Console-only, or
SoundEngine-only route must be typed and executable on its correct host and must
return an explicit host boundary elsewhere. Verification strength may differ by
route, but its declared result must never claim more than the strongest
available evidence.

## Typed Query Construction

Typed Query Construction is Gateway-Owned Request Construction for read-only
functions and Topic filters. Existing closed query flags remain valid; nested
sources, transforms, predicates, returns, subscription options, and event
matches use typed facts rather than caller-serialized JSON. The Gateway
materializes the existing versioned query or subscription request.

A bounded read-only WAQL expression may remain an exact caller-supplied domain
expression. Its enclosing request, URI, return projection, result cap, framing,
and syntax restrictions remain Gateway-owned. Preserving this expression does
not permit raw WAAPI arguments or options.

## Typed Request Construction Core

The Typed Request Construction Core is the shared deep Module that compiles an
exact versioned schema into bounded scalar, object, array, branch, handle, and
Open Typed Map actions. Functions, queries, and Topics reuse this structural
engine instead of maintaining three input grammars.

The Core constructs facts only; it does not merge their lifecycles. A read-only
function or query dispatches directly after validation, a Topic creates a
bounded subscription, and a mutation enters immutable Preview and authorization.
Dedicated operation Adapters may add business terminology and stronger checks
without creating a second parameter system.

## Operation Draft

An Operation Draft is mutable, task-capability-bound composition state. It
records Business Declarations, revisions, validation evidence, and one
crash-safe handoff reservation. It has no Wwise side effect and is not
permission to mutate a project. Invalid declarations are atomic: they do not
advance its revision or change its durable bytes.

The Operation Draft Store is separate from the immutable transaction store.
Draft authority does not authorize Preview confirmation or execution.

## Canonical OperationRequest

The Canonical OperationRequest is the closed, versioned mutation request parsed
by `operation_registry.py`. It is the single downstream truth for preparation,
native dispatch, project/runtime guards, verification, and cleanup. Composer
materialization must re-enter the same authoritative strict parser used by the
internal Preview ingress; it is never trusted as a pre-parsed bypass.

## Historical OperationRequest Record

A Historical OperationRequest Record is a previously sealed, complete
OperationRequest retained only for offline evidence and archive replay. It is
not accepted by the production Gateway as a new mutation. Versioned archive
readers preserve historical auditability without retaining a second production
input system.

Machine-readable JSON remains an internal representation for canonical
requests, immutable evidence, fixtures, and developer-only schema validation.
The single-input rule applies to model-facing product interfaces, not to
repository storage formats or maintainer diagnostics.

## Migration Wave

A Migration Wave is a reviewed group of exact Registry operations that can
reuse Composer infrastructure without merging their business contracts. Each
operation still owns its typed Adapter, version lanes, safety checks, and
verifier. A shared native URI never places operations in the same wave.

## Generic Manifest Call

A Generic Manifest Call is a reviewed compatibility route for a reflected
WAAPI function that has no dedicated named operation. Its normal model-facing
input is an exact-URI, reflected-schema-derived typed codec: zero-value and
bounded inline shapes are materialized by the Gateway, while complex shapes use
the Generic Schema Composer. Raw `args` and `options` are never model inputs.
A dedicated named operation may replace the generic route when stronger
business semantics or verification are required. Read-only Generic Manifest
Calls are outside the mutation-input model.

## Change Preview

A Change Preview is an immutable transaction artifact derived from a Canonical
OperationRequest and current live evidence. It binds project/runtime guards,
pre-state, authorization, execution-at-most-once, verification, and cleanup.
Preview creation has no mutation side effect. Confirmation or durable policy
authorization is still required before execution.

## Boundary summary

- The user describes business outcomes.
- The Agent performs Business Orchestration and supplies closed Business
  Declarations.
- Gateway-Owned Request Construction owns every normal WAAPI input.
- Gateway-Owned Operation Input constructs every normal mutation request.
- The Operation Composer compiles draft-shaped Business Declarations.
- The Operation Registry owns field, type, version, and limit truth.
- The Operation Draft Store owns mutable composition state.
- The transaction store owns immutable Preview and authorization state.
- The dispatcher and verifier own native execution and business evidence.
