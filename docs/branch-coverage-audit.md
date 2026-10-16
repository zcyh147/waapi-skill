# Five-version branch audit — issue #164

Baseline: `37957b1d8fa81967475e158a0a1733d9fc4c3e87`. This is an
**incomplete coverage audit**, not a new functional PASS or an assertion that
all reflected business branches are implemented. No Wwise or Fresh process ran.

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
All unreviewed field mappings, compiler attribution and branch-specific program,
real and Agent evidence remain unknown. Shared `evidence_defaults` applies to
every structural branch; it grants no inherited route-level PASS. The explicit
business rows keep their own implementation and evidence fields separate.

## Findings and remaining review

- **High: independent Effect ShareSet creation.** The source-reviewed baseline
  has owner-effect placement only. Work Unit child placement is absent from
  that public operation. Repair belongs to #169; no prohibition is invented.
- **High: initial GameParameter fields and conditional dependencies.** Preserve
  #168/#167 as unverified/incomplete business combinations, respectively. These
  statuses come from approved requirements, not newly executed tests.
- **High: branch-to-business mapping remains unreviewed across the surface.**
  Existing route depth and historical execution claims do not close these rows.
  Resolve native branch to public value/compiler/boundary and attach exact
  evidence in a separately scoped review. The audit intentionally cannot certify
  full branch coverage merely because every URI has a route.
- **Medium: legacy implicit schema children.** Unfamiliar nested keyword rows
  retain their complete value and digest, notably 2021.1 SoundBank structures.
  Their semantics need explicit review before any coverage claim.
- **Unknown: reference-edge reachability and exhaustive business combinations.**
  The definition graph is sealed and enumerated, but this checker does not prove
  each referenced definition is publicly reachable. The business baseline is a
  sourced seed, not an exhaustive Cartesian product or closed business catalog.

After repair merges, regenerate the structural ledger and explicitly reconcile
`branch-coverage-business-baseline.json` against the new public contracts and
matching tests. Its baseline candidate is retained so a missing baseline branch
cannot silently turn into a current-candidate completion claim. New substantial
work discovered in review needs scheduling, not automatic implementation.

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
The generator itself is offline and has no Wwise imports or network client.
Full combined Program/Non-live gates remain the integration owner's release
step; these focused tests grant no Wwise or Agent behavior credit.

## Bounded next audit pass

This deliverable completes reusable enumeration and drift detection, **not the
full mapping review requested by #164**. Do not close that issue from this
ledger. The next pass should work by contract family, not manually review every
occurrence:

1. Join existing `native_surface_policy.json` selector mappings and versioned
   business registries to matching native pointers. Reuse exact identical
   schema/contract digests across versions; retain version-specific exceptions.
   Validate a representative positive and a removed-selector negative through
   the actual Gateway before assigning reviewed mappings to the family.
2. Prioritize the plugin graph family after #169 and the creation/property
   families after #167/#168. Record placement, target type and mode independently
   of the schema mapping. Attach exact new tests and real evidence when available;
   preserve the historical baseline as history.
3. Group residual unmapped branches by public contract and native schema digest,
   separate deliberate documented safety/host/version boundaries from missing
   mappings, and propose a bounded follow-up for each large unresolved family.
   Reference expansion and the ten legacy implicit-child occurrences are a
   small independent structural follow-up. No new functional ban is justified
   by absence of evidence.

The committed full ledger is intentionally reproducible diagnostic evidence:
it retains occurrence provenance and exact drift comparison. It can later be
replaced by a reviewed content-addressed schema table without changing the
public checker semantics; doing so is an artifact-size optimization, not
coverage progress.
