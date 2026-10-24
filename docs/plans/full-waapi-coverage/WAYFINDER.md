# Full WAAPI business coverage: scope and acceptance

Date: 2026-10-17. Baseline: merged PR #173, `07c20232`.
Planning only: no product code, tests, Wwise launch or Fresh execution changed.
The user confirmed the practical destination: eliminate cases where Wwise
supports a valid condition, parameter or use but the Skill rejects it because
its wrapper is incomplete. This is broader than finishing an audit inventory.

## Destination

Build the next spec and English implementation tickets around this direct flow:

1. Reflect the available functions, Topics and exact parameter schemas.
2. Compare their valid inputs and uses with the public Gateway contracts.
3. Fill missing coverage through the existing business-declaration architecture.
4. Verify that Skill routing and Gateway discovery reach the right public seam.
5. Prove the resulting behavior with proportional tests.

The direction is settled; no additional general design interview is needed.
This planning checkpoint is not completion of the implementation effort.

## Confirmed scope

- Cover Wwise 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1, preserving exact build
  and host provenance. Console and ordinary Authoring capabilities are included;
  the current packaged subset must not define the supposedly complete universe.
- Previously excluded ordinary Authoring layout/model/window/signal interfaces
  are included. The user explicitly continues to exclude the new Authoring
  `ak.wwise.ui.cli.executeLuaScript` and `ak.wwise.ui.cli.launch` additions.
  This does not remove existing public Core/CLI Lua capabilities.
- Preserve the three modification policies and Gateway-owned request construction.
  Scope expansion does not authorize raw-client bypass or arbitrary native input.
  Existing dangerous-field restrictions remain explicit and must not be used to
  relabel missing ordinary functionality as prohibited.
- Valid fields, enum meanings, optional/default behavior, nested collections and
  alternative shapes are included. Use live object/class/plugin metadata where
  API schemas do not describe applicable fields or activation conditions.
- Include meaningful target-type, placement, create/edit and dependency variants:
  an owner-local effect and an independent ShareSet are different uses even when
  they share a native API. Do not invent an infinite Cartesian product of values;
  every supported semantic distinction still needs an explicit mapping.
- Every newly found wrapper omission stays in this implementation effort. A
  research or inventory ticket may finish, but its implementation/evidence gaps
  must transfer to linked implementation tickets, not disappear into a future
  out-of-scope backlog. A broader exclusion requires a new user decision.

## Concrete acceptance

- Each in-scope reflected field/alternative and meaningful business use maps to
  a public Gateway input, its construction/validation path, correct routing and
  required verification evidence. A pointer to a whole module is insufficient.
- Wwise-supported conditions and parameter shapes must not fail merely because
  a Skill parser/builder has not implemented them. Invalid combinations still
  receive accurate structured errors; host/version absence needs native evidence.
- The public path works without agent-authored scripts, guessed native requests
  or reading repository implementation. Keep SKILL.md concise; Gateway schemas
  own operation fields, choices and continuations.
- Missing mappings, unimplemented branches and missing required evidence remain
  visible failures of the overall coverage check. Replace the audit tool's
  current fixed incomplete response with evidence-driven completeness during
  implementation; do not change it in this planning phase.
- Removing one branch, enum alternative, version or required proof must make the
  coverage check fail. Merely generating the same inventory does not establish
  that the interface supports it.
- Native unsupported, environment-blocked, implemented and verified are distinct.
  The current 2021 ShareSet packaged boundary is unresolved implementation work,
  not proof that native Wwise cannot create it through any supported route.
- Delivery can be incremental, but the implementation parent is not complete
  while an in-scope Skill-origin omission remains. Do not equate planning,
  inventory completion, or a passing representative example with total coverage.

## Cost-controlled validation

Use full five-version deterministic program coverage as the main gate, including
public parser/schema/dispatch paths and invalid-input controls. Use deterministic
real Wwise tests sequentially where native effects or version differences need
proof. Missing environments or licenses are blockers, never passing evidence.

Fresh remains Mac-only and bounded by separately approved counts. Select cases
for distinct routing and interaction mechanisms, not one Agent per API or version.
Before Fresh, test the real Gateway/Broker/archive chain deterministically,
including legitimate errors and refinements. No Fresh attempt is authorized by
this planning document. Preserve raw failures and separately scoped evidence.

## Reuse before recollection

The [historical evidence review](../../research/authoring-reflection-reuse-2026-10-17.md)
confirms complete five-version Authoring URI lists from September. Full Authoring
schema sets were not retained in those roots. After the two excluded Authoring
Lua/launch functions, at least 48 known missing version/schema rows remain:
23 on 2024.1 and 25 on 2025.1. Retained core, Topic and command schemas are reusable
where exact provenance matches. Identical URI lists do not prove identical host
schemas; shared Console/Authoring shapes also need evidence or fresh collection.

The user authorizes opening matching Authoring versions sequentially when
necessary for read-only reflection. Prefer existing complete evidence first;
use owned disposable projects, preserve user work, and never alter a user's
current project to collect schemas. Current core collector still passes a
live --version override and is incompatible with config-only Gateway; repair
that collection path in the implementation phase or use an already-supported
public read path. Do not weaken connection binding.

## Next handoff

The specification is published as [Complete WAAPI business coverage across Wwise 2021.1–2025.1](https://github.com/zcyh147/waapi-skill/issues/174). Local copy: [SPEC.md](SPEC.md). Implementation tickets have not been created.

Proceed to `/to-spec` and `/to-tickets`, using English tickets and actual
missing-branch IDs. Organize implementation by reusable mechanisms: metadata
conditions; missing parameter/enum/nested shapes; object topology and placement;
ordinary Authoring additions; routing and outcome verification. Each ticket owns
all applicable five-version branches and evidence, rather than only an audit
report. Carry every unresolved discovery into the implementation graph.
