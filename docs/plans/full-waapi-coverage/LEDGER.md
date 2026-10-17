# Branch completion ledger

This is the implementation of #176, using the existing
`tests/maintenance/branch_coverage_audit.py` maintainer CLI. It does not extend
runtime WAAPI execution or grant implementation credit to later tickets.

Run the audit with the developer interpreter:

```bash
poetry run python tests/maintenance/branch_coverage_audit.py --check --require-complete
```

Exit 0 means the requested check succeeded; `--require-complete` additionally
requires every obligation to reach an accepted terminal state. Exit 1 means
invalid input or reproducibility drift. Exit 2 means a valid, reproducible but
incomplete scope. Without `--check`, the CLI writes the current derived ledger.
Historical business baselines and original run records are never rewritten.

## Independent denominator

The ten complete native catalogs are loaded and validated independently of the
execution partition. Route identity includes release, native host, exact build,
item kind and URI. Schema identity adds the exact input/output pointer and
alternative discriminator. A missing public route remains a row.

The traversal retains properties, enum and Boolean alternatives, union members,
optional presence, defaults, legal empty values, collection cardinalities,
constraints and unknown nested keywords. Capital `OneOf` is retained as native
source spelling and gets an explicit semantics obligation. Reachable local and
external definitions are traversed as a bounded per-route/per-section graph;
every reference edge, including recursive edges, remains explicit. Visiting a
shared definition once does not prove its separate caller edges.

Installed XML observations are in `docs/branch-coverage-condition-sources.json`.
They retain original corpus digests, source-file digests, occurrence paths and
exact snippets. They are installed-source facts, not live applicability or
behavior evidence. Existing/new object condition modes, enum/range/reference
alternatives, five plugin kinds and placement modes remain distinct. Reflected
object types also retain separate creation/edit applicability obligations.
Internal types and unresolved plugin placements are not presumed creatable.

Existing-object plug-in condition rows belong to #177 without a blanket #179
creation dependency. Their built-in Effect/Source/System classes can be bound
to independently located existing instances, or to instances created through
an already supported public route. This establishes no whole-class, placement
or native evidence credit. New-object plug-in conditions still depend on
#177 and #179, and plug-in topology rows retain #177/#178 dependencies. If an
exact existing class cannot be reached through those routes, retain that
obligation and add its actual implementation dependency rather than omitting
it or requiring every existing edit to wait for all creation modes.

## Ownership

`docs/branch-coverage-ownership.json` is an exact URI/kind roster. It assigns
functional work to #177–#193; #193 is a bounded explicit utility roster, not a
fallback. Source condition and target distinctions add their own exact owners
and dependencies. #194 remains additional routing/harness work and #195 remains
acceptance. Unknown ownership cannot complete; it requires a bounded same-parent
implementation child and an acceptance dependency.

The existing v2 source-attribution, policy and historical business fields remain
available. A route/family/parent mapping, a test filename, or a historical PASS
never completes a descendant obligation.

## Exact bindings and evidence

`--bindings FILE` accepts `waapi-skill.branch-bindings/v1` with a `bindings`
object keyed by exact obligation ID. Each binding pins the branch's native
shape, public route and current public-route digest; the generated public
`gateway_argv`; and exact construction, validation and verifier source symbols.
Their selectors name the exact branch pointer. Referenced definitions can add
an exact `observation_pointer` and `reference_chain` of ledger reference IDs for
their caller context. Direct fields cannot be redirected to siblings; array
indices and pattern-property keys must match the exact native path. Selected
union children are resolved from their native catalogs and checked with the
existing bounded schema validator. Unknown semantics remain unverified. No raw runtime input
route is created by this maintainer format.

An `approved_boundary` disposition can prove correct rejection instead of
successful dispatch. Its authority must be either the exact native/public host
mismatch, or one of the external command hooks explicitly retained by SPEC and
#184 (`generateSoundbank`/`tabDelimitedImport`). The original policy selector and
approval source digests remain visible. A real public rejection, exact input,
matching error and no target dispatch are required. A prohibited hook must be
present by its exact approved name and value in the executed argv, and its
rejection must name that same hook; unrelated input errors cannot certify it. Host checks also require the
matching original getInfo host/build. The native route remains present and the
state is verified boundary behavior, not native absence or execution credit.
Other branches receive no inherited credit. Legacy `intentionally_blocked`
labels are not approval: childOfReference, copy/move replace and ordinary
parameter gaps remain functional work.

Each evidence category references a preserved JSON artifact by path, byte
SHA-256 and exact executed test node. An optional `record_index` selects one
original JSONL record without editing it. Records carry the current relevant
source identity, exact native shape/context, final node outcomes and executable
assertions against preserved observations. Assertions support exact values,
omission and collection cardinality. Generic Gateway success is insufficient:
input/result branches require their own native observation, and enum/Boolean/
null/empty alternatives must assert the actual alternative value. Public input
must match the executed Gateway continuation. Related artifacts are separately
hash checked.

`--requirements FILE` accepts `waapi-skill.branch-evidence-requirements/v1`,
with a `branches` map keyed by exact obligation ID. Each reviewed row pins
`native_shape_sha256`, a nonempty `reason`, and `categories` containing program
plus whichever of native, live_metadata and fresh apply. A missing or stale
policy remains unresolved. The committed policy is intentionally empty while
functional owners establish mappings. There is no implicit native campaign for
every scalar. `additional_requirements` can add evidence requirements. A sealed
controlled scope explicitly requires program only.

Program receipts bind the exact executed public argv, native dispatch URI,
observation pointer, and public `agent_result` assertion. `dispatch_pointer`
selects one call from composed/multiple native calls; `observation_pointer`
selects its precise input/output field. Public projections can differ from raw
native results. Alternative value and field must be established by the same
assertion. Presence, null, empty values, cardinality and type variants enforce
their own semantics. Defaults additionally require the explicit omitted input
at `default_omission_pointer`.

Native effect evidence consumes original finalized
`waapi-skill.host-category-evidence/v3` records. It reads the actual producer's
top-level Git `candidate`, `host.version` components, `host.is_command_line`,
source `hash_before`/`hash_after` and `mtime_before_ns`/`mtime_after_ns`, plus
`residual_state` cleanup. Exact passing nodes must explicitly link the original
sealed observation artifact digests; assertions read those original artifacts
under `/observations/`, not a copied summary or family status. Their digest map
is bound by `native_observations_sha256`. This mapping still needs source and
behavior review; a historical family PASS by itself cannot create it.

Live metadata uses the existing ScenarioLifecycle/v3 producer separately:
summary/lifecycle, ready/getInfo, status receipt, original public metadata argv,
exit/result receipts, source seals and cleanup, all checked against the original
external file seal. It grants live_metadata credit only, never native effects
or Fresh. The compatibility fixtures preserve original native records and are
reader tests, not new coverage evidence.

Explicit reviewed reuse is available through a sealed
`waapi-skill.branch-evidence-equivalence/v1` attestation. It binds original and
successor candidate identities, exact branch ID/native shape/host/build route,
original evidence digest, binding semantics digest, and unchanged relevant
source digests. `relevant_sources` must include the construction, validation and
verifier sources plus public launcher/Gateway; the reviewer includes all other
behavior dependencies. Original receipts retain their source seals. For
category records, the reader retrieves exact source bytes from the original Git
candidate; metadata uses its original plan source seals. Current source bytes
must still match. `equivalence` bridges a preserved branch receipt;
`native_equivalence` bridges an original producer's Git identity to the current
source identity. It accepts one sealed descriptor or an exact original-evidence
digest map for multiple producer records. Source-only native absence requires
both native hosts and exact `absence_observation_pointers` into each host's
original artifact, with explicit omission assertions. Present or unobserved
fields cannot become absence through a label. Other source metadata requirements
declare exact hosts. No wildcard, family or inherited parent equivalence is accepted.
Changed relevant source, native shape, evidence, candidate or mapping invalidates
reuse without altering the historical verdict.

Selected Fresh requirements fail closed until #194 supplies the existing formal
archive bridge. A harness label alone cannot pass. This tool neither launches
Fresh nor authorizes its expense.

## Computed states

| State | Meaning |
| --- | --- |
| `unresolved` | Exact mapping, reviewed requirements, ownership, applicability or semantics remain unresolved. |
| `missing_implementation` | A native route or its exact public construction/validation/verifier binding is absent or stale. |
| `implemented_unverified` | Exact bindings exist; required executed evidence is missing, stale or invalid. |
| `environment_blocked` | Exact implementation exists and a preserved final BLOCKED record identifies an unavailable prerequisite. |
| `verified` | All exact bindings and required evidence pass for this candidate and context. |
| `proven_native_absence` | A source-only applicability obligation has matching native absence evidence and explicit alternative analysis. A present reflected route or missing Skill implementation cannot use this state. |
| `approved_exclusion` | One of the two explicitly excluded Authoring ui.cli additions, bound to SPEC and exact URI. Other existing safety boundaries remain visible for exact functional-owner mapping and proof. |

Missing implementation takes precedence over an environment blocker. Neither
absence nor exclusion grants execution credit. Reproducibility is reported
separately from these coverage states.

## Storage and controlled proof

The readable inventory references an adjacent deterministic gzip companion for
large native row sets. Repeated route, shape and equal record fields are indexed
before compression. The CLI transparently hydrates every exact row and checks
compressed bytes, canonical row digest, count and regenerated content. This is
storage deduplication only, not semantic or evidence equivalence.

`--controlled-scope FILE --scope-sha256 SHA` is a separately sealed test-only
scope. It pins complete native catalog seals, exact selected routes and every
obligation beneath them; empty, stale or incomplete membership is rejected.
Its output explicitly says `scope_kind: controlled` and
`product_coverage: not_evaluated`. Controlled evidence cannot grant product
credit.

The controlled positive exercises the real public Gateway parser/executor with
injected clients: `request-schema` followed by its generated continuation, on
both native hosts for 2024.1 and 2025.1 ping, including both Boolean results.
Additional real public Gateway examples exercise a nonzero query input, multiple
native calls, a projected public result and reachable definition context; Media
Pool text/number filters distinguish actual native union alternatives. A Console
UI wrong-host rejection proves an exact retained host boundary. These fixtures prove checker mechanics and program behavior, not native execution.
Corruption controls remove or change scope members, public inputs, exact
selectors, mappings, verifiers, required evidence, artifacts and candidate/native
identities; parent PASS, broadened exclusions, forged native labels and stale
equivalence claims cannot complete the scope.

## Functional-ticket use

Start from the exact obligation IDs assigned to the ticket. Add reviewed
requirements and exact mappings; retain all other rows as unresolved:

```bash
poetry run python tests/maintenance/branch_coverage_audit.py \
  --output /tmp/ticket-177-ledger.json \
  --bindings /path/to/177-bindings.json \
  --requirements /path/to/177-requirements.json \
  --require-complete
```

Repeat with the same arguments plus `--check` to verify the saved result. A
finished ticket can still produce exit 2 because other product obligations
remain open. Use controlled scope only for checker tests, never to rename a
partial product result complete. The committed inventory currently has 272,313
obligations: 270,363 unresolved, 1,834 missing implementation and 116 exact
approved exclusions. These are accounting rows, not distinct API or bug counts.

The integrated #177/#181/#188 partials retain every original native obligation
identity, shape and owner. The public source partition now contains 874 exact
version/function/Topic rows; the 25 new 2024.1/2025.1 layout read and mutation rows
remain explicitly assigned to #188 as migration required in the interface-depth
policy. Existing completed family seals remain unchanged. Public route presence
reduces missing-route accounting only; no branch bindings, evidence requirements,
native effects or ticket completion are certified by this reconciliation.

The second partial integration retains closed empty-layout registration and
removal alongside switching; original nested layout/OneOf semantics remain
unresolved. A separately captured exact condition product receipt may establish
program behavior for its own candidate only. Its native requirement remains
missing, and it does not change this default product ledger or certify another
candidate's branch evidence.

The third integration adds scoped get-or-create-view on 2024.1/2025.1 and close
on 2025.1 only, and moves existing Media Pool getFields to a bounded fixed
metadata command. The native denominator and exact ownership stay unchanged;
56 newly linked obligations move from missing implementation to unresolved.
No separate product evidence is recaptured or inherited for this successor.

The fourth integration adds only these exact public route keys:
`2024.1|function|ak.wwise.ui.layout.undockView` and
`2025.1|function|ak.wwise.ui.layout.undockView`; no existing key is removed.
Forty original native obligations move from missing implementation to unresolved.
All 272,313 ID/shape/owner tuples, ten independent catalog seals, five original
definition files, detailed native selector policy and completed family seals
remain unchanged. All25layout rows stay migration required under #188.
Structured2022–2025ShortID support retains2021mapping as unresolved; original
native alternatives and all remaining requirements remain in the denominator.
Neither these route linkages nor controlled producer/lifecycle tests establish
native effects, exact accepted branch evidence or ticket completion. The new
shared Authoring adapter and condition native fixture remain not launch-ready.
