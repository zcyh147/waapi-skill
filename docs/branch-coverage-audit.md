# Five-version branch audit — issue #164

Baseline: `37957b1d8fa81967475e158a0a1733d9fc4c3e87`. This is an
**incomplete coverage audit**, not a new functional PASS or an assertion that
all reflected business branches are implemented. The audit generator launches no
Wwise or Fresh process; separately completed native evidence is explicitly scoped
below.

## Reproduce

From the repository root, using the developer Python:

```sh
python tests/maintenance/branch_coverage_audit.py
python tests/maintenance/branch_coverage_audit.py --check
python tests/maintenance/branch_coverage_audit.py --check --require-complete
```

The last command deliberately exits 2 while branch mapping remains incomplete.
A reproducibility check exits 0 only for the exact generated ledger; drift exits
1. `--output PATH` supports independent snapshots without overwriting the
committed ledger. The JSON uses one record per line for reviewable diffs.

The generator independently reads all five Console functions/topics/schema
files, narrow Authoring command/topic/core supplements, and definition graphs.
It compares exact version/type/URI identities against the execution partition
and public interface inventory. Same-count substitutions fail. It preserves
both Console and supplementary schema occurrences when they share a URI;
these are provenance occurrences, not additional API coverage.

Every schema node, enum value, union alternative, nested collection, optional
presence/absence and reference edge has a stable source/subject/pointer ID and
content digest. Referenced definitions are enumerated once per document rather
than infinitely expanding recursive schemas. Unknown nested keywords remain
visible. Bounds, required lists, and scalar validation constraints are sealed
in their schema-node digest. Annotation text is not treated as a business branch.

Route rows link public schema digests, named operations, host restrictions,
execution policy, declared verifier and program-case identifier. Branch rows
link those route rows. **That link is not a native-to-public field mapping.**
The v2 source join now records current registered contract builders and materializers,
family entrypoints for non-Adapter lanes, and verifier entrypoints. The 45 native
surface policy rules contribute 484 declared selector dispositions. Exact selector
occurrences are distinguished from descendant scope attribution. Neither is an
enum-value correspondence or an execution result. Branch-specific program, real
and Agent results therefore remain unproven unless a separate evidence row says
otherwise. Shared `evidence_defaults` applies to
every structural branch; it grants no inherited route-level PASS. The explicit
business rows keep their own implementation and evidence fields separate.

## Current reconciliation and remaining review

`branch-coverage-business-baseline.json` stays frozen at its original candidate.
`branch-coverage-current-business.json` is the separate current reconciliation:
ShareSet placement, owner Effect topology, Source placement, initial
GameParameter fields and conditional reference prerequisites are independent
rows in every version. Each row points to public contract, compiler, preflight
where relevant, verifier and test definitions. A test definition never grants a
PASS. Native evidence names its candidate and exact scope. The current registry
index additionally retains binding, declaration, discovery and safety dimensions
for every registered contract reached from the native route index; it is a
source-backed catalog, not an assertion that their Cartesian product was tested.

ShareSet now has public deterministic native PASS on candidate `df8e0610` for
2022.1–2025.1, with the lifecycle paths recorded in the current reconciliation.
This proves the fixture's independent Work Unit child lifecycle, not every plugin
class or property combination. 2021.1 remains an explicit `object.set` boundary.
GameParameter public same-call creation also passed all five versions on
candidate `90018ae0`, including independent readback of the created GUID and
Min/Max/InitialValue. Its earlier registry-level feasibility remains separate
history. The public condition is restricted to reviewed live GameParameter
metadata; arbitrary class dependency grammars remain outside this evidence. Conditional references distinguish
atomic `object.set` activation from explicit prerequisite transactions for
`object.setReference`; unsupported dependency expressions are not guessed.

`reviewed_snapshot_seal` compares the reviewed depth-policy contract hashes with
the current parser, operation and continuation contracts using the same hash
inputs as the depth inventory generator. A stale review remains historical
attribution and earns no current credit. The integration owner must perform the
normal reviewed regeneration after runtime changes stabilize. This audit neither
rewrites that policy nor bypasses its validator.

On the current generated snapshot there are 849 routes and 24,310 structural
occurrences: 870 exact policy-selector occurrences, 2,425 descendant-scope
attributions and 21,015 without a selector join. The 484 policy dispositions
are declarations before expansion across versions and duplicate profile
occurrences, so they are not a coverage percentage. There are 471 current
registry contract records and 1,331 residual groups. These are generated
accounting counts, not passing test counts.

Every unresolved structural occurrence has a `residual_group`. Groups use the
public family plus the native schema digest; each retains route IDs, kind counts,
selector relation counts and sample pointers. Shared definition nodes are grouped
by their own digest until reachability is reviewed. The full branches remain the
provenance ledger; this is an indexed join, not a duplicate branch inventory.

| Priority | Family / branch question | Concrete next review and completion evidence |
| --- | --- | --- |
| P1 | Object graph / creation / reference | Map target-type × placement × create/edit mode independently. Join each class field and dependency encoding to compiler and verifier. Preserve 2021 boundaries; use exact positive and incompatible-target tests. |
| P1 | Media import / build / CLI | Review import replacement/default enums, nested file rows and build options individually against closed declarations. Require omitted-versus-explicit default tests and immutable-preview/verifier evidence. |
| P1 | SoundEngine / runtime / host UI | Bind every enum/union value to its business meaning, host restriction and lifetime cleanup. Command success alone does not establish project effect. |
| P1 | Query / metadata / Topic | Trace selector expressions, return projection and reference reachability; map event options and timeout/count boundaries. Distinguish schema validation from semantic readback. |
| P2 | Result schemas and shared definitions | Resolve definition edges from exact public contracts, then assign reachable result alternatives to bounded validators. Unreachable is a finding to justify, not an inferred prohibition. |
| P2 | Legacy unfamiliar nested keywords | Review the retained implicit children, especially 2021.1 SoundBank structures; add explicit enumeration semantics if they encode executable branches. |

Within these families, the machine groups identify exact schema digests and
missing evidence. Selector `intentionally_blocked` is a declared policy boundary,
not proof every descendant alternative reaches the intended failure. `mapped` or
`normalized_equivalent` is also only the policy's declared disposition here.
The existing policy validator enforces selector completeness and required
normalized-equivalence test pointers, but this audit does not execute those tests
or invent per-branch results. Unmapped means unproven, never unsupported.

## Residual family inventory

Counts below include schema/result nodes and profile occurrences, not unique
business behaviors. The exact route IDs, schema hashes and pointer examples are
in `residual_groups`; `family_findings` supplies each group’s review question.

| Family | Groups | Occurrences | No selector join | Source entrypoint |
| --- | ---: | ---: | ---: | --- |
| generic-cli-console | 37 | 2039 | 1228 | [`cli_console_business.py`](../skills/waapi-skill/wwise_waapi/cli_console_business.py) |
| generic-core-media-build | 12 | 487 | 487 | [`media_build_business.py`](../skills/waapi-skill/wwise_waapi/media_build_business.py) |
| generic-core-project-object | 38 | 1067 | 1067 | [`core_business.py`](../skills/waapi-skill/wwise_waapi/core_business.py) |
| generic-core-remaining | 27 | 615 | 615 | [`core_business.py`](../skills/waapi-skill/wwise_waapi/core_business.py) |
| generic-core-runtime-inspection | 59 | 1403 | 1403 | [`runtime_inspection_business.py`](../skills/waapi-skill/wwise_waapi/runtime_inspection_business.py) |
| generic-dedicated-route-boundary | 84 | 3421 | 1260 | [`operation_registry.py`](../skills/waapi-skill/wwise_waapi/operation_registry.py) |
| generic-fixed-command-audited-deep | 10 | 481 | 478 | [`operation_registry.py`](../skills/waapi-skill/wwise_waapi/operation_registry.py) |
| generic-fixed-query-metadata | 29 | 2236 | 1916 | [`metadata_discovery.py`](../skills/waapi-skill/wwise_waapi/metadata_discovery.py) |
| generic-host-ui-debug-waapi | 16 | 533 | 533 | [`host_ui_debug_business.py`](../skills/waapi-skill/wwise_waapi/host_ui_debug_business.py) |
| generic-soundengine-runtime | 71 | 1599 | 1599 | [`soundengine_business.py`](../skills/waapi-skill/wwise_waapi/soundengine_business.py) |
| generic-topics | 80 | 4396 | 4396 | [`topic_business.py`](../skills/waapi-skill/wwise_waapi/topic_business.py) |
| generic-zero-input-audited-deep | 31 | 712 | 712 | [`operation_registry.py`](../skills/waapi-skill/wwise_waapi/operation_registry.py) |
| shared-definitions | 837 | 5321 | 5321 | `resources/manifest/<version>/definitions.json` |

The indexed contract and compiler links refine these family entrypoints wherever
a registered Adapter exists. Remaining pointers are explicitly family attribution,
not fabricated per-leaf compiler locations. Each family’s concrete open question:

- **generic-cli-console:** CLI option spelling, repeatable bank/platform/language rows, default omission and hook exclusions need exact declaration-to-native correspondence; process success is not generated-bank verification.
- **generic-core-media-build:** Import path/source replacement and SoundBank inclusion/build alternatives need independent public value mapping and output verification, including partial results.
- **generic-core-project-object:** Reference/property, identity, destination and conflict-mode alternatives need exact target-type and dependency mappings; route attribution does not prove each nested value.
- **generic-core-remaining:** Remaining core contracts need URI-local field/enum mapping; inherited family materializer attribution does not identify which declaration emits each native leaf.
- **generic-core-runtime-inspection:** Inspection selector/filter and runtime-control alternatives need bounded readback and lifetime-specific evidence; result-schema validation is weaker than state verification.
- **generic-dedicated-route-boundary:** Named operation alternatives must be separated by target type, placement, mode and verifier; plugin owner/ShareSet and class/instance property semantics cannot inherit family PASS.
- **generic-fixed-command-audited-deep:** Fixed commands need native option and result-alternative mapping to their actual Gateway branch; a fixed CLI command name does not prove every schema alternative.
- **generic-fixed-query-metadata:** Query selectors/return projections and metadata result alternatives need exact closed/advanced contract correspondence, default bounds and reference-target reachability.
- **generic-host-ui-debug-waapi:** UI command/registration and debug option alternatives need fresh catalog, correct-host and cleanup boundary mapping; catalog snapshots cannot establish current command availability.
- **generic-soundengine-runtime:** Game object, playing/transport capability, enum and numeric union meanings need exact business encoding, revocation/lifetime and wrong-handle negatives per API.
- **generic-topics:** Subscription match/options, publish payload alternatives, count/time/idle bounds and cancellation cleanup need per-topic mapping; publish-schema enumeration alone does not prove delivered events.
- **generic-zero-input-audited-deep:** Zero-input routes still have host restrictions, return alternatives, side effects and paired cleanup; empty args establish no branch-specific effect verification.
- **shared-definitions:** Resolve every reference edge from its route/profile to the definition document before assigning public reachability; structurally identical definition nodes alone establish no reachable business combination.

## Audit completion status

Completed: independent five-version route/schema accounting; complete reuse of
declared selector dispositions; current contract/binding/declaration/compiler and
verifier attribution; exact historical-seal drift; separate business reconciliation;
candidate-scoped native evidence; finite family/schema gap assignments; and
generator/checker rejection tests. These complete the source-accounting and gap
deliverables, without declaring functional branch coverage complete.

Still unreviewed: exact native leaf-to-public value equivalence outside the joined
selectors; alternative-specific equivalence even within a mapped parent; reference
reachability; exhaustive target-type/placement/mode combinations; and program,
native and Agent evidence not explicitly scoped by the current reconciliation.
The 21,015 unjoined occurrences are assigned review work, not silently dropped
and not declared unsupported. Final issue closure is the integration owner’s
decision after final-candidate seal reconciliation and combined gates.

## Why ShareSet was missed

The following conclusions are from repository history, not a guess about prior
Agent intent:

1. Commit `0ee0470d` introduced `operation_plugin.py` with a documented scope of
   Source children, Wwise 2022.1 fixed Effect references, and later EffectSlot
   creation. Its `PLUGIN_KINDS` contains only `source` and `effect`; the versioned
   placement path describes an owner's effect chain. Independent Work Unit
   ShareSet placement was not one of those branches.
2. Commit `bee27b8b3e70e03554b01c96d36f5d51d7867f07` changed the entire
   `named-object-creation-graph` family from `migration_required` to
   `already_deep`. The policy grouped `object.create`, `object.createPlugin`,
   `object.set`, and `object.setRTPC`, with representative graph/Weather evidence.
   It did not add a placement-by-target business inventory.
3. The current `docs/operation-composer-migration-inventory.md` records one
   `object.createPlugin` row for 2022.1–2025.1. The current interface-depth policy
   similarly records the family as deep. `test_operation_plugin_registry.py`
   covers Source children and fixed/appended owner effects; those examples do
   not prove independent ShareSet placement.

Thus the demonstrated failure is **business-branch omission in a route/family
completion model**. The records do not show a specific independent-ShareSet row
being tested and falsely marked PASS. Calling all historical evidence false
would be unjustified; using that evidence as full placement coverage is also
unjustified. A readback accepting `EffectShareSet` as a type is not proof that
Work Unit child creation is exposed.

## Validation

The focused maintainer suite tests optional/enum/union/collection enumeration,
same-count route substitution, removal of a branch mapping, an invented ShareSet
completion claim, unknown nested keywords, and CLI drift/incompleteness exits.
It exercises public generator/checker inputs and outputs without runtime mocks.
The generator imports offline registries only and never constructs a network client
or launches Wwise. Missing selector policy, removed enum/union occurrences and
removed mapping-index entries are rejection cases in addition to URI substitution.
Full combined Program/Non-live gates remain the integration owner's release
step; these focused tests grant no Wwise or Agent behavior credit.

## Reading the generated joins

- `branches[].mapping` joins `mappings`; `mapping_relation` distinguishes an
  exact selector from descendant attribution. Result fields without selector
  policy remain explicitly unjoined.
- `branches[].route` joins `routes`; `public_contracts` joins `contract_index`
  where an Adapter exists, otherwise it points to the Gateway schema entrypoint.
  `compiler_attribution` says whether the pointer is a registered compiler or a
  family entrypoint requiring more detailed attribution.
- `contract_index[].definition`, route compiler/verifier pointers and current
  business pointers join `source_index`, which pins file, symbol, line and digest.
  Every source digest is rechecked by the public checker.
- `branches[].residual_group` joins the finite follow-up groups. No group gets
  implementation or test credit from a route's historical depth label.

The audit deliverable accounts for available source mappings and assigns the
remaining proof work. It does not certify complete behavior coverage. Keep
`--require-complete` failing until that separate review is complete. New product
work found during the review needs its own bounded issue and acceptance criteria.
