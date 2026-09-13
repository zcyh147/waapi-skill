# CRUD interface closure audit and bounded repair plan

Date: 2026-09-13. Baseline: `2c714912e8383538290dd46fd61af56526c8e4fe`.
Working branch: `codex/harden-batch-field-diagnostics`.

## Decision and scope

The business-compiler design remains usable. The audit found inconsistent
public field-selection and value-disclosure paths, not a reason to replace
the Gateway, Draft store, immutable Preview, authorization or execution engine.
Repair the existing Interface and its shared helpers, rather than adding a
second field-authority system or relying on stronger prompt wording.

This is an **audit and proposed plan**, not completed remediation. The earlier
uncommitted changes to `gateway.py` and
`tests/unit/test_object_graph_business_gateway.py` improve batch failure
diagnostics only; they were preserved unchanged during this audit. They do not
close the field-selection seam. In particular their instruction to submit a
short field meaning is not the intended final mutation interface.

The scope covers the five pinned versions, the complete 23-URI
`ak.wwise.core.object.*` reflected union, named object CRUD/graph/plug-in/RTPC
operations, `audio.import`, and adjacent property-taking Core contracts.
The companion [version/evidence report](crud-five-version-evidence-audit-2026-09-13.md)
contains the full URI/version table and historical evidence partition.
This is not an exhaustive security or semantic audit of every WAAPI parameter,
SoundEngine call, UI command, Topic, plug-in, object type or user workflow.

Methods: source call-chain inspection, actual Adapter contract imports for
each supported version, five packaged metadata-schema inspections, and a
synthetic in-memory enum-binding probe. No Wwise, network client, Fresh Agent,
Program gate or full Non-live suite was started. No user Draft, configuration,
installed Skill or demonstration project was changed. No old transaction was
replayed. Audit scripts imported the developer library; they were not public
Skill workarounds and receive no live or Agent acceptance credit.

The design criterion comes from [ADR 0003](../adr/0003-gateway-compiles-business-declarations.md):
the Agent chooses closed business outcomes, while native tokens, scope,
request construction and execution planning belong to the Gateway. A string
called a "business value", an opaque final handle, or a historical PASS does
not establish that the complete acquisition path satisfies that criterion.

## Confirmed findings

### F1 — Bulk `object.set` combines discovery with mutation field selection

Affected: `object.set` on 2022.1–2025.1, specifically
`draft-declare-existing-batch`.

The call chain is public parser -> `dispatch_business_existing_batch` ->
`discover_metadata` -> exact-label preference or remaining lexical candidates
-> require one candidate -> `bind_live_field` -> atomic business declaration
-> normal materialization/check/Preview. Two related leaks are present:

1. `--field-meaning-value` takes a model-authored meaning directly into field
   selection for the proposed change.
2. `--field` silently reinterprets an unknown fixed field as a discovery query.
   Thus a typo is not necessarily rejected as an unknown parameter.

Sources: [parser](../../skills/waapi-skill/scripts/gateway.py#L2950),
[fallback](../../skills/waapi-skill/scripts/gateway.py#L18056),
[resolution](../../skills/waapi-skill/scripts/gateway.py#L18114),
[contract](../../skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py#L206).
The operate reference explicitly tells three-or-more-target workflows not to
perform field discovery first
([routing](../../skills/waapi-skill/references/waapi-operate.md#L65)).

The weather failure safely rejected the batch; it is not evidence of arbitrary
WAAPI writes or a broken authorization boundary. Nevertheless a unique search
result is not proof that the submitted label was a disclosed fixed parameter.
Candidate counts are bounded returned-candidate counts, not proof that every
possible field was exhaustively searched.

**Repair:** keep meanings in discovery only. A batch declaration consumes
strict fixed business fields or already selected, exact-object-bound field
handles plus values. Unknown fixed names fail with structured alternatives;
do not strip `Action`, introduce fuzzy aliases, or silently reroute the input.
Preserve atomic failure, revision semantics and exact per-object checks.

### F2 — Raw token/class binding remains reachable before the handle

Affected: `audio.import` and `object.create` in all five versions;
`object.createPlugin` on 2022.1–2025.1.

`draft-bind-field` publicly accepts `--token` and either `--class-name` or an
object handle. Its handler checks `adapter.supports_field_binding`; that flag
is true for the three operations above. It then binds the supplied exact token
against live metadata. Audio import explicitly advertises this continuation;
creation/plug-in routes can still reach the handler even when their preferred
continuation instead advertises field discovery.

Sources: [parser](../../skills/waapi-skill/scripts/gateway.py#L3054),
[handler](../../skills/waapi-skill/scripts/gateway.py#L17488),
[Adapter flags](../../skills/waapi-skill/wwise_waapi/business_adapters.py#L492),
[Audio continuation](../../skills/waapi-skill/scripts/gateway.py#L26498).
The existing public Gateway import test explicitly supplies `Sound` and
`CustomGain`, then asserts successful binding
([test](../../tests/unit/test_audio_import_business_gateway.py#L543)).

The live name/type/range/dependency checks remain valuable: this is not a raw
unvalidated setter. The deficiency is requiring the caller to obtain and
retype native implementation facts to acquire the handle in the first place.
Our earlier observation that import rejects unknown fixed fields remains true,
but is insufficient to certify its entire custom-property path.

**Repair:** enable operation-compatible discovery for import using existing
object handles or semantic kinds; use selected type handles for plug-ins.
Once parity is demonstrated, remove the model-facing token/class binder and
its Adapter opt-ins, not just its visible help text. Keep `bind_live_field`
as an internal implementation primitive. Simply toggling import's discovery
flag is insufficient: the current discovery handler's catch-all eligibility
branch is unlink-specific, so import needs an explicit reviewed property/
reference eligibility case.

### F3 — Common time fields are promised but not wired; units differ by entry

The domain and `COMMON_BUSINESS_FIELDS` contain `fade_time_ms` and `delay_ms`,
but the operation-local fixed field maps and graph compiler do not expose or
materialize them. `normalize_common_business_fields` has no runtime call site
outside its own definition/export. `volume_db`, in contrast, is genuinely
implemented in both graph and import compilers and is not a missing feature.

The batch-only `_parse_bound_field_business_value` recognizes time suffixes
for tokens `FadeTime` and `Delay` and converts milliseconds to seconds.
Single graph/import field-handle declarations use `_parse_business_value`
instead. Also, this conversion currently checks the token and numeric type,
not the owning class/version; a similarly named custom field should not
inherit a time-unit interpretation merely from its spelling.

Sources: [common vocabulary](../../skills/waapi-skill/wwise_waapi/business_declarations.py#L82),
[public graph fields](../../skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py#L18),
[compiler](../../skills/waapi-skill/wwise_waapi/object_graph_business.py#L465),
[batch quantity parser](../../skills/waapi-skill/scripts/gateway.py#L15226),
[graph scalar parser](../../skills/waapi-skill/scripts/gateway.py#L15329).

**Repair:** a small shared, reviewed field-definition table should own public
name, type, units, applicable object kinds, version availability and native
conversion for common outcomes. Add the already-promised Action durations
only after their per-version semantics/applicability have evidence. Do not
make those fields available on every object just because the table is shared.
Keep operation-specific structural semantics separate. Dynamic fields remain
live-discovered; no exhaustive hardcoded Wwise property database is proposed.

The generic metadata schemas do not establish Action's concrete unit/range or
ActionType-dependent availability. The current resource audit has not found a
complete five-version Action field snapshot. This is an evidence gap, not
proof that 2021/2023/2024 behave incorrectly.

### F4 — Enum labels are discarded at the shared field-handle seam

All five packaged `getPropertyInfo` result schemas support
`restriction.values[].displayName` alongside `value`. The normalizer preserves
only the values as `enum_choices`. Discovery returns that reduced restriction;
numeric property inputs still require numbers. Thus a returned enum can be
type-safe but insufficiently explained for the Agent to translate user intent.

Sources: five `resources/manifest/<version>/schemas.json`, exact URI
`ak.wwise.core.object.getPropertyInfo`, JSON path
`resultSchema.properties.restriction.oneOf[3].properties.values.items.properties.displayName`;
[restriction reduction](../../skills/waapi-skill/wwise_waapi/business_declarations.py#L1679),
[value validation](../../skills/waapi-skill/wwise_waapi/business_declarations.py#L951),
[discovery reply](../../skills/waapi-skill/scripts/gateway.py#L17909).

A synthetic in-memory probe called the actual `bind_live_field` in all five
version contexts with enum rows `First mode: 0`, `Second mode: 1`. Every
result retained only `{"enum_choices": [0, 1]}`. These are fixture labels,
not claimed Wwise properties, and the probe proves reduction behavior only.

**Repair:** disclose bounded label/value choices from the same metadata
snapshot as the field authority. Support deterministic selection of a returned
choice, never model-guessed numeric enum meanings. Duplicate/missing labels
must remain distinguishable and require an explicit valid choice; do not
invent English names or add fuzzy matching. Preserve existing numeric values
where explicitly disclosed/selected. This is shared value-presentation work,
not a reason to alter the WAAPI executor.

## Adjacent concerns, not yet proven execution defects

### R1 — Ordinary object-list names remain a caller-owned token

`object.set` exposes `object_list` and `draft-clear-object-list --list-name`.
The contract calls it an exact user-owned Wwise list name; normalization checks
token syntax, while preparation reads that exact list and rejects RTPC/Effect
lists in favor of dedicated operations. Missing or malformed list readback is
not silently treated as an empty list. This is narrower than arbitrary payload
construction, but a user who did not name a list still leaves the Agent with
an internal-name selection problem.

Sources: [declaration](../../skills/waapi-skill/wwise_waapi/object_graph_business_contracts.py#L245),
[syntax](../../skills/waapi-skill/wwise_waapi/operation_object.py#L554),
[preparation](../../skills/waapi-skill/wwise_waapi/operation_registry.py#L5823).

Audit this selection seam separately using existing relationship/type
derivations. Only add a bounded list-selection mechanism if its authoritative
source is established; do not assume `getPropertyInfo` enumerates every owned
object list. Preserve supported list capabilities and dedicated-operation
boundaries. No broad list-state or list-verifier rewrite is justified here.

### R2 — Read-only matching is not equivalent to a mutation escape

`query-object --include-field` and `object.isLinked` also resolve field meanings
from live metadata. They own bounded read projections and do not authorize a
later mutation. Their zero/multiple candidate errors and returned field labels
can be aligned with the shared diagnostic design, but do not force ordinary
reads into Drafts or require mutation-style confirmation for each query.
The existing exact-ID selection gate for subsequent mutations remains intact.

## Paths inspected without the same confirmed leak

- `setProperty`, `setReference`, `setLinked`: public changes require bound
  field handles; discovery fixes object scope and filters property/reference/
  unlink suitability. Unknown declaration keys are rejected.
- `setRTPC`: exact owner field handle, bound control input, closed curve/mode;
  supports-RTPC filtering and later metadata checks remain present.
- `createPlugin`: its preferred type/field discovery path uses type/class-bound
  handles; F2 concerns the alternative raw binder, not removal of that working
  type-discovery design.
- `setRandomizer`, `pasteProperties`, `setStateProperties`: closed Core plans
  use field handles with source/object-scope checks. `setStateGroups` uses
  bound object roles. No direct field-meaning write path was found there.
- `copy`, `move`, `delete`, `setName`, `setNotes`: closed role/outcome contracts;
  rename/delete object-capability boundaries remain in their normal path.
- Common graph/import fields and field-handle writes reject token collisions;
  graph existing-object fields reject wrong object scope and platform conflict.
  Draft check revalidates stored objects, fields and types before Preview
  ([check](../../skills/waapi-skill/scripts/gateway.py#L15048)).

These are bounded code observations, not a claim that every hidden bug or every
property capability in those operations has been proven absent. Exact user
artifacts such as a supplied tab-delimited import file are not automatically
treated as guessed property inputs; this repair must not remove those lanes.

## Why previous coverage did not catch this

Some tests assert the existing permissive behavior: import raw token binding,
bulk `fade_time` fallback, and continuation-only absence of `--token` in
creation. They can pass while the ownership rule is violated elsewhere.
The generated inventory classifies `field_values` as live-bound authority and
business scalars; that classification alone does not prove how the handle was
acquired ([inventory](../../tests/maintenance/interface_depth_inventory.py#L723)).
Historical real CRUD success proves exercised effects, not these negative
public-input invariants.

Add regression assertions for the **whole public acquisition path**, alternate
commands, and per-operation field/value parity. Do not merely change a prose
classification or update a golden until green.

## Proposed implementation order and acceptance

### 1. Close field acquisition and batch selection (F1 + F2)

- Reuse existing field discovery and `BusinessHandleRegistry`; allow bounded
  multi-target discovery if needed so batch users do not manually repeat a
  long per-object sequence. Return per-row selected handles and copy-ready
  continuations. Existing scope/revision rules continue to apply.
- Batch accepts fixed names or selected field handles; remove unknown-name
  fallback and mutation-time meaning matching. Keep meanings as searches.
- Give import an explicit compatible discovery path, then retire public raw
  token/class binding for every operation, including non-advertised commands.
- Preserve object/class distinctions, project/build/task binding, metadata
  freshness, atomic Draft updates and Preview authorization. Do not globally
  reuse an object-bound handle across unrelated targets just to save calls.
- Align schema, parser, continuation and routing together. Do not retain the
  old mutation grammar as an automatic fallback.

Acceptance: public fake-client regressions across supported version lanes;
the original prefixed Action meanings can search or receive clear diagnostics,
but cannot directly drive a modification. Unknown names, zero/multiple
candidates, forged/wrong-scope/stale handles and partial-row failures leave
Draft bytes/revision unchanged. Existing final native requests stay equal for
equivalent valid declarations.

### 2. Complete common field/value disclosure (F3 + F4)

- Centralize common field definitions without moving operation-specific graph,
  import or plug-in topology logic into a giant generic compiler.
- Reuse existing fixed fields; wire Action duration outcomes where supported
  and unify reviewed unit conversion across relevant declaration forms.
- Preserve enum labels and explicit choice authority. If a persisted field
  representation changes, version/validate it explicitly: old records must
  return a bounded recreate/refresh result, not corrupt the whole Draft store.
  No full-state migration, state-directory move or authorization relaxation.
- Inspect ordinary list selection (R1) before calling CRUD closure complete;
  fix confirmed interface leaks locally, and keep unresolved evidence explicit.

Acceptance: schema/parse/materialize/Preview parity for each public common
field in each applicable version; absent values cause no new edits; duration
units, wrong object kinds, negatives/nonfinite values, duplicate meanings,
enum labels/values, label ambiguity and metadata drift have focused negatives.
Custom plug-in fields remain usable without raw token/class input.

### 3. Proportionate verification and cutover

- Run failing-focused tests first, then affected files. On the final stable
  implementation run the fixed five-version Program gate once. Before merge,
  run the required Non-live gate for the resulting shared runtime/contract
  change; do not run either full gate after every parameter edit.
- Most of this is pure parser, binding and compiler behavior. Use actual
  exported Gateway commands with injected fake clients and isolated state,
  not a second semantic harness or a prompt-retry loop.
- If the Action mapping still lacks pinned evidence, first search retained
  traces. Only unresolved native semantics justify short sequential matching
  Console probes in disposable Action fixtures: metadata, one targeted change
  and readback, source integrity and cleanup. Do not reset/re-import Weather.
- No full Fresh Agent, dual-platform 12-case, or multi-version semantic campaign
  is planned. If changed Skill routing itself needs Agent evidence, isolate
  that decision later to a minimal existing-harness offline probe; it is not
  justification for a broad real campaign. No such probe ran during this audit.
- Native Windows tests are conditional on changed shell/platform-sensitive
  code; shared pure-Python evidence must not be relabeled Windows execution.
- Keep historical failures and archived records. Update generated inventory
  evidence only from the reviewed final interface, after tests stop. Synchronize
  the demo Skill only as a separate explicit deployment step.

## Implementation size and stop conditions

This is a contained Interface repair spanning parser/continuation, Adapter
contracts, shared field/value helpers and tests, not necessarily one small
`.py` edit. No evidence currently calls for a new transaction state machine,
new broker, new harness, wholesale metadata re-reflection, or all-API rewrite.
If implementation requires changing execution ordering, authorization,
verifier meaning, or native version topology, stop and reassess that separate
scope rather than quietly expanding this plan.

Audit-only result: two research documents added; the earlier two-file
diagnostic patch remains pending. No new test pass count, live success or
complete encapsulation claim is made.
