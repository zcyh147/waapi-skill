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
policy remains unresolved. The committed policy currently has one exact 2025.1 Console moveSingle
result-shape requirement; other policies remain unestablished. There is no implicit native campaign for
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
obligations: 270,427 unresolved, 1,770 missing implementation and 116 exact
approved exclusions. These are accounting rows, not distinct API or bug counts.

The integrated #177/#181/#188 partials retain every original native obligation
identity, shape and owner. The public source partition now contains 878 exact
version/function/Topic rows; the 29 new 2024.1/2025.1 layout read and mutation rows
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
remain unchanged. All 25 layout rows stay migration required under #188.
Structured 2022–2025 Short ID support retains 2021 mapping as unresolved; original
native alternatives and all remaining requirements remain in the denominator.
Neither these route linkages nor controlled producer/lifecycle tests establish
native effects, exact accepted branch evidence or ticket completion. The new
shared Authoring adapter and condition native fixture remain not launch-ready.

Ticket #188 additionally has fake-tested owned Mac Authoring strategy plumbing in
the existing ScenarioLifecycle/sandbox/HeadlessLifecycle path. Exact build,
private default bottle, copied-project roundtrip, readiness identity and cleanup
failure controls passed without launching an installed tool or native client.
This grants no branch/native effect credit. The existing driver now installs the
Mac owner after exact successful collection with fake-only controls. Native
Windows ownership, cross-family integration and the remaining layout contracts
and observations stay open; the Authoring permission-window hold remains active.

The fifth partial integration refreshes current source seals for peak/raw/header
continuations, live metadata selections, unconditional selected-field drift
guards and original condition/Authoring lifecycle plumbing. Its exact public
route set remains unchanged at 874 version rows / 216 unique URIs. Every native
ID/shape/owner tuple, independent catalog, original definition and detailed
selector/completed-family seal is preserved, with no state transition or new
verified/native/Fresh credit. All 25 layout rows retain #188 migration-required
ownership. Controlled condition cleanup now waits for final pytest reports;
native execution, Windows ownership and cross-family proof remain outstanding.
Definition Short-ID version-proof inconsistency is a new explicit open #183
acceptance item with shared #181 work, not an exclusion or denominator change.
No old product receipt is transferred to this integrated source candidate.


Ticket #188 has a further code-only partial for exact-target docking/redocking
and signed splitter movement on 2024.1/2025.1. Docking binds the same scoped
layout, view and target, preserves floating and already-docked paths, and checks
serialized parent/child order and orientation plus independent rectangles.
Splitter movement derives its axis from the exact parent stack and rejects
clipped, resized, perpendicular or stale effects without replay. The original
native schemas and contradictory definition graph remain unchanged. Four exact
version/function rows are added; all 29 layout rows retain migration-required
ownership under #188. This branch's source inventory is 878 public rows / 218
unique URIs; combined generated artifacts remain integration-owned.

Focused fake evidence is retained without erasing failures: splitter controls
passed 25; target-kind docking controls passed 8; the combined product selection
reported 214 passed / 1 failed / 64 deselected because its exact owner roster
missed the two new URIs. The corrected owner-only control then passed 1. Existing
mutation regression reported 65 passed / 1 failed / 40 deselected because the
Program manifest count needed its new splitter file; that exact manifest control
then passed together with the owner control (2 passed). These are deterministic contract/effect-oracle tests,
not owned native observations, branch completion or release acceptance. Nested
setLayout construction, 2025 reset semantics, exact native interpretations and
consolidated host-specific validation remain open under the GUI launch hold.

The dock/splitter partial was merged with released integration `dcf0ae11`; its
post-merge focused selection passed 192 tests, including the additive 230-node
Program manifest. Review then exposed a missing preservation guard: four new
public controls all failed because the requested geometry could be certified
while an unrelated existing view was removed or retagged. Their original RED
run is retained. The fix snapshots every canonical instance in preview-local
prestate and verifies exact view identities/types only for dock/moveSplitter.
Those four controls then passed; three positive controls permit floating/redock,
old wrapper removal and changed dock flags; the 30-case full positive movement
matrix plus pre-execute unrelated-view drift controls passed. Container-ID or
whole-view-state equality is not an extra post-write prerequisite. Original
native behavior proof and complete nested/reset scope remain outstanding.

A further #188 constructor partial extends the existing setLayout Draft with a
closed local-key stack/view blueprint. The Gateway generates and freezes unique
node identities at declaration, validates a bounded single tree, derives native
keys, checks fresh view-type availability before Preview and execution, and
verifies all requested nested fields and child order after registration. Empty
registration remains available. A distinct optional workspace name preserves
Layout.Name separately from the temporary lookup name; omission uses the lookup
name as a Gateway convenience. Matching installed SDK documentation supports the
field distinction, not native divergent-name write or overwrite acceptance.

Focused source validation passed 47 tests across blueprint contracts, existing
empty registration/removal, profiles, original definition obligations, exact
owner and additive 231-node Program roster. Original schema/fixture failures are
retained. A later maximum-depth control exposed a genuine readback mismatch at
16 stack levels (one failed); the declared business bound was tightened to 14
without changing the existing native-result limits, and that control passed.
Native definitions, their capital OneOf/allOf and per-version sidebar enum
inconsistencies remain untouched. This is a partial constructor, not complete
nested-layout coverage. Typed editor/sidebar/window/history creation and state
changes, reset branches and owned effect evidence remain #188 work under the
unchanged GUI hold. No old native receipt is transferred to this source.

Immutable constructor checkpoint `57d885c2` subsequently passed its complete
focused selection: 48 tests, including an actual public Preview/execute/readback
at the advertised 14-level edge. An additional explicit 15-level valid-Draft
control rejects before opening any client or writing; that control and the
14-level accepted edge passed together (2 passed). The nesting ceiling is solely
a Gateway resource bound, never a native Wwise restriction. Legitimate deeper
native arrangements remain an explicit resource gap requiring reviewed support
or an approved boundary, without automatic branch-completion credit.

The immutable `ccd743dd` depth successor passed 49 focused tests. A subsequent
near-byte-bound constructor exposed two independent resource defects: compiled
layout expansion exceeded bounded readback, and an otherwise accepted request
could exceed the existing 256 KiB Draft seal or 24 KiB terminal reply. Original
failed runs remain retained. The constructor now separately discloses 112 KiB
business-value and compiled-layout bounds, a 256 KiB rendered terminal-request
ceiling, and a narrowly selected 280 KiB terminal envelope derived from the
existing Draft allowance plus ordinary framing. Small constructors and other
operations retain 24 KiB. Exact closed-constructor validation selects the larger
budget; no caller flag, native schema change, global output increase, truncated
request or rebuilt agent_result is introduced. Declaration/Preview and stored
execution requests check rendered fit before writes.

Verification compares every requested field and order independently, retains
full bounded readback and immutable expected state in the journal/Preview, and
reports digests plus at most sixteen useful mismatch paths instead of repeating
whole layouts in assertions. Fake roundtrips cover near-bound ASCII, multibyte,
quote/backslash and scoped-session enrichment; separate controls reject deep
rendering before writes and oversized business values before a client. These
resource ceilings remain Gateway gaps, not Wwise limits or completion of larger
native branches. Downstream Broker/Fresh acceptance of the larger bounded reply,
full typed state/window/history/reset construction and owned native effects
remain outstanding under the absolute GUI/Console/Fresh hold.

The coherent constructor-capacity regression passed 85 focused fake tests,
including the original verification digest, strong/weak tamper and cleanup
controls, exact profile/native obligations/owner and 231-node Program roster.
This validates source behavior only; native effects and downstream reception
remain pending.

Clean capacity checkpoint `3e7b0b7a` passed 86 tests on its frozen source. An
immediate public create/verify/inspect control then exposed that layout-inspect
still equated the native lookup name with serialized Layout.Name. The original
RED is retained. Inspection now presents separate layout_name/workspace_name
values; its existing capability keeps the exact lookup identity plus full
observed workspace document/hash. No capability schema migration or stale/same-
layout guard was weakened. Both version lanes pass creation, verification, fresh
inspection and a separately previewed removal by the original lookup name (2
passed). Workspace/nested-document/lookup drift and foreign lookup authorities
sharing a serialized workspace name, together with the complete scoped-read
Gateway file, passed 71 tests. This is deterministic source proof, not native
divergent-name write acceptance. Larger-output Broker/archive acceptance is
tracked under the already-dependent OPEN #194; no Fresh run is authorized.

Workspace successor `b5c555d9` passed 86 focused frozen tests. Parent review then
found that the native contents contract legitimately permits omitted Layout:
inspection issued a capability before failing with opaque KeyError text. That
public RED remains retained. A separate availability/type guard now rejects
omitted contents deliberately before any handle storage/issue, without restoring
lookup/workspace equality. Both omitted-content version controls, all scoped-read
tests, divergent create/reuse and stale/foreign authority controls passed 75
tests. Earlier passing runs remain partial source evidence; no missing case or
native acceptance was inferred from them.

#193 bounded source slice on exact integration `8dfdcc76` exposes the missing
tone collection choices through existing host-plan CLI/Draft composition. Only
`ak.wwise.debug.generateToneWAV` is changed: waveform channel empty sets map to
explicit zero for 2024.1/2025.1, and explicit marker emptiness maps to [] for
2025.1. Omission, empty and populated forms remain distinct in request-schema,
Draft continuation and immutable Preview; waveform choice remains unchanged.
Conflicting/duplicate/undisclosed/native inputs fail before mutation, and all
three modification policies retain their existing gates. Original public parser
RED is retained; the first corrected full public lifecycle control passed, and
the full host-business selection passed 120 fake tests before final fixture
format alignment.

A separate source defect remains owned by #193: generic tone verification accepts
the result schema with verified=false even without an output WAV. Independent
simulated file observations do not establish product effect proof. The exact
remote empty-choice and artifact-verifier criteria were copied additively to
local ticket19; complete bounded artifact/effect verification, matching native
evidence, complete WAL delivery and remaining host contracts stay open. No
native/Console/Authoring/Fresh launch or generated inventory update occurred.

The final explicit-collection source selection passed 124 fake tests, including
the complete host-business file, existing isolated transaction verifier boundary,
exact adapter registration, operation catalog and reviewed schema seal. It grants
closed-input construction/policy evidence only; tone artifact/effect and native
verification remain pending implementation and acceptance under #193.


## #193 bounded Tone artifact verifier checkpoint

The successor to host-collection source `4f366334` adds exact-target prestate and
prewrite guards plus independent bounded RIFF/PCM16/float32/header/frame/silent
channel/empty-cue observations through the existing public transaction and
artifact seams. Known incorrect or missing artifacts fail instead of receiving
schema-only success. Valid unchanged output may verify its requested observable
state, retaining separate `created`/`changed` facts. Synthetic full-chain tests
establish implementation behavior only; no native, Fresh, family seal or whole
#193 credit is asserted. Active signals, fractional rounding, populated marker
semantics and anonymous/Ambisonic encodings remain explicitly incomplete.

The public large-marker reproduction establishes a further #193 terminal
capacity defect (`VERIFY_SUCCESS_SUMMARY_BUDGET_EXCEEDED` after one dispatch),
without changing output allowances. Its implementation follows this coherent
checkpoint; downstream Broker/archive delivery remains additionally owned by
#194. Full #193/WAL and #188 state/native scope stay open. Original REDs and
intermediate compatibility failures are retained in separate `/tmp/waapi-tone-*`
roots and the worker handoff; no native process or launch was used.

The sixth combined integration preserves every original native ID/shape/owner,
all ten independent catalog seals, five original definitions, detailed native
selector policy and historical completed-family seals. Exactly four public keys
are added: 2024.1/2025.1 function ak.wwise.ui.layout.dockView and
ak.wwise.ui.layout.moveSplitter. No key is removed; 64 original native obligations
move only from missing implementation to unresolved. All 29 layout rows remain
migration_required under #188. No verified/native/Fresh branch credit is added.
The original f72 scalar batch and strict-reader program milestone remains tied
to its original source; it is not loaded into this default ledger. Contextual
query failures, source closure/admission and partial layout constructors retain
all unproven applicability, native effects and downstream delivery obligations.


The seventh combined partial merges only fixed query `b95bddbb`, reference
hierarchy/classifier safety `7ed7a105` and Tone artifact verification `c253c5ae`.
Reconciliation retains every original 272,313 native ID/shape/owner tuple,
independent catalog/definition, detailed native policy and historical family
seal. All 878 public route keys remain unchanged; there is no branch-state
transition or native/Fresh acceptance credit. The actual Program roster is 241
unique entries without whole-file/exact-node overlap. Unknown reference target
classifiers, native query type spelling/2021 Short-ID mapping, Tone waveform and
populated-marker semantics, larger terminal delivery and all other original
scope remain owned. Source-level artifact verification and explicit boundaries
are partial implementation, not completion of those obligations. Existing
product receipts are not transferred to this successor.


The r7 reproducibility checks pass for depth and release; branch
`--check --require-complete` exits 2 because the unchanged product scope remains
incomplete. Original focused `9cfa110f` reports 372 passed / 1 stale schema-seal
failure / 11 Windows-only skips; the exact five-version guidance-seal repair
`b1fadd6e` passes its entire 16-test file separately. Original failures stay
preserved, no runtime changes follow the combined source run, and no broad or
native acceptance is inferred from these focused results.


## #193 terminal-capacity and path-race successor

The successor to `c253c5ae` makes the original long-marker request survive exact
bounded terminal verification using the existing constructor-capacity mechanism.
Actual public maximum-aggregate/maximum-count ASCII, UTF-8 and escaping controls
preserve the immutable request, exact agent_result, journal digest and actual
main stdout with session context. Other/unbound shapes and small requests cannot
claim the larger bounded budget. No marker input limit was reduced and no global
output ceiling was raised. Broker/archive reception remains additional #194 work.

Public filesystem fault injection reproduced and normalized post-hash unlink and
root stat/resolve disappearance. Separate resource tests exposed missing header
and marker overhead in the old audio+44 estimate. The new prewrite reservation
accounts accepted format/framing and requested UTF-8 cue/label metadata while
retaining unknown native encoding/extra chunks/fractional rounding explicitly.
The reserved maximum fmt size is Gateway resource policy, not observed writer
behavior. UTF-8 maximum-plan LIST framing already fits its bound; no unsupported
encoding inference or new native credit follows. Full #193/WAL and #188 remain
open, and original REDs stay retained in distinct `/tmp/waapi-tone-*` roots.


## Incremental product capture inputs

The first reviewed requirement is the exact 2025.1 Console
`ak.wwise.cli.moveMediaIdsToSingleFile|/resultSchema` row in
`docs/branch-coverage-requirements.json`. It requires both public program proof
and independent native file effects. It grants no completion credit by itself;
other rows and alternatives remain open. Freeze this policy and the relevant
source before capture.

Use the existing `tests/support/media_id_branch_evidence.py` producer:
`prepare_media_id_capture` selects the existing exact public test, and its
pytest finalizer emits original `bindings.json`, `requirements.json` and
`program.json`. Keep these in a fresh ignored capture directory. Their actual
Gateway argv include that run's state directory and transaction identity; do not
replace these with portable placeholders or commit machine-local paths.

Evaluate the complete product ledger using the maintainer CLI with explicit
`--bindings <capture>/2025.1/bindings.json`,
`--requirements docs/branch-coverage-requirements.json`,
`--output <capture>/product-ledger.json` and `--require-complete`. Repeat the
identical command with `--check` for reproducibility. This overlay keeps every
product obligation; it is not a controlled-scope acceptance. Exit 2 is expected
while required evidence or other branches remain incomplete. At that R26 checkpoint the default
unbound inventory remained an inventory, not the evidence-bearing overlay.

Retain the exact command and input hashes alongside the overlay so a reviewer
can reproduce the evaluated result. Missing or stale artifacts stay missing;
only the existing strict readers may grant evidence credit. Attach native
evidence only after an independently reviewed matching run. Whole-file source
equivalence and literal argv equality remain unchanged.


## Portable default evidence inputs (#195)

Ordinary audit generation and `--check` now select the reviewed
`docs/branch-coverage-evidence-index.json`. The first entry imports exact R26
moveSingle program/binding/requirement/capture bytes under the existing
`tests/fixtures/branch-evidence/product/` tree. A separately sealed projection
changes only the program artifact locator to a relative bundle path. Original
argv, candidates, source seals, assertions and results are unchanged and never
executed. The imported program has no nested reader artifact dependencies.

This is partial accounting: its historical program proof is stale for current
sources and no native attachment exists. Neither the index nor a historical
PASS grants current verification, descendant credit or completion. Missing or
malformed selected inputs fail explicitly; unlisted obligations remain visible.
Duplicate exact bindings and projection changes beyond the locator are rejected.
The existing committed program-plus-native requirement remains unchanged. An
explicit override that omits a policy row leaves that branch unresolved in the
existing evaluator; the imported historical policy is provenance and never
fills the missing row. A conflicting present policy is rejected.

`--bindings FILE` remains the explicit maintainer override; `--binding-index FILE`
selects a reviewed alternative portable index and cannot be combined with
explicit bindings or controlled scope. Both modes use the same evaluator;
relative evidence descriptors resolve against their binding bundle base.
Index/document integrity is sealed separately from candidate source identity,
preventing a receipt/index self-reference. New selection logic lives in the
already source-sealed audit module. Temporary output/check receipts validate
this component; committed inventory regeneration belongs to integration.


## R39 regression integration and retained gaps

Runtime merge `c51371d1` preserves the four accepted component tips without
fixups (21 exact file blobs). Its two runtime files repair modern EffectSlot
Render proof for explicit retarget/clear/planned references and equivalent
certified platform views; the remaining changes are fixtures and an opt-in
owned diagnostic. All public schemas/seals for 153 versioned operation rows
across 34 named operations are unchanged from `695344f1`. No new public route,
raw request or client fallback is added.

Four serial inventory generate/check commands passed once. The generated delta
is one registry source hash, three existing source-index entries and the native
candidate identity. All 79 source members, 91 source-index members, native
catalogs/descriptors, 272,313 compressed obligations, ownership, requirements,
exclusions and evidence states remain exact. Product coverage remains incomplete;
staged program controls do not grant a branch transition, family/leaf credit or
native acceptance. Exact staged results are recorded in the test inventory.

Root's original `695344f1` failed subset ended 976 passed / 466 failed, distinct
from the retained earlier full Program failure on `c18225d9`. At that handoff,
no replacement broad gate or merger pytest ran. The no-media Japanese merge intent remains
required unimplemented/unproved #180/#181 work; its original request and exact
boundary are retained beside a platform-only positive. Source-anchored follow-up:
`/tmp/waapi-r39-language-followup.md`.

The separate `34a64ac1` native active-source diagnostic remains FAIL and its
category blocked: all three two-source path joins matched saved active GUIDs,
while every active source was first in both source orderings. Root's method
review supports proceeding with a narrow 2021 file-backed Sound path-to-source
join, with program order-permutation and ambiguity controls; another native
boot merely to obtain a non-first active source is unnecessary. No resolver is
implemented or generic coverage credited by this diagnostic. Plugin/no-file,
equal-path, unlinked-view and active-choice-transition cases remain #181 work;
neither current boundaries nor this result prove native absence. See the
retained native follow-up.

## R40 scoped successors and unchanged completion accounting

Runtime merge `495f8a7f` combines accepted graph `026f9181`, Voice `89d0ef9f`
and Tone `49e4b69e` without fixups; all nine component blobs match. Root's
original R39 failed subset remains **456 passed / 10 failed in 103.95s**.
The ten graph fixes and Voice/Tone controls have separate staged receipts in
the test inventory; they are not a replacement broad gate or aggregate PASS.

New empty Voice language is validated native construction context, with
before/after selected-language and actual empty-Source proof. It is not a
persisted Sound language or localized Source. Existing-merge language effects
remain required #180/#181 work. Staged Voice creation followed by Source-plugin
creation on the real bound GUID already exists; atomic planned-parent Source
construction/native validity remains #179/#180/#181 work, not native absence.

Stationary sine verification uses frozen requested frequency/dB gain, bounded
streaming comparison and an explicit numerical policy. Retained native samples
are offline controls; their original outcomes are not regraded. No new native
or Fresh acceptance follows. Other waveforms/envelopes and all remaining #193
obligations stay open; no active-source component is included.

Only four object.set 2022–2025 business-disclosure leaves change, describing
the construction-context boundary. The reviewed aggregate public seal and its
contract references refresh; all 153 Registry machine seals remain exact.
Four serial generate/check commands passed once. Source membership remains
79 entries / 91 indexed entries / 329 full-file closure entries; all 272,313
native obligation bytes, ownership, requirements, statuses and evidence remain
unchanged. Inventory reproducibility grants no branch/family/leaf transition.
Root owns publication and the next settled gate; no merger pytest ran.

## R41 Source composition, file-backed selection and reimport preservation

Runtime merge `edbc24cb` integrates exact accepted reimport `aaa91777`, planned
Source `8ec0925d` and query/disclosure `01a65041` from published `e80d9250`.
All 17 component files are preserved: 13 exact blobs and four clean shared-file
compositions, without fixups. Source plugins can be composed beneath planned
Sound/Voice through the existing 2022–2025 object.set producer, with independent
Source-language intent, actual GUID/class/parent/field proof and closed child
sets. This is program-tested construction; atomic native acceptance and the
2021 alternative remain required #179/#180/#181 work.

The 2021 query derives each selected file-backed Sound's active Source from a
unique full canonical path join in an explicit platform/language view. Existing
query predicates/relationships, ordering, requested bounds and result-detail
continuations remain; 64 is an internal batch size, not a public result cap.
Existing-SFX reimport independently binds the selected Source and its own bytes,
revalidates populated or empty preconditions before writing, and verifies the
actual post-write selection. The setter now discloses existing source linkage,
no unlinking and possible effects on other linked platforms. Unlinked views,
same-path/plugin/no-file/transition cases, Source-plugin selection and remaining
language/merge/preservation obligations remain open; no generic #181/#182 credit
is inferred. The integrated import verifier intentionally changes; only the
Source component alone preserved that original AST.

The initial four serial inventory generate/check commands passed once. All 153
Registry machine seals remain exact. Only reviewed Source graph/2021 query disclosure
seals and corresponding contract references change, plus the setter linkage
contract references and source/hash/line/candidate refreshes. All 272,313 native
obligation bytes, IDs, ownership, statuses and evidence remain unchanged;
79 source members/91 indexed members stay exact and the full candidate closure
now contains 330 files, including the new resolver. Policy retains its original
formatting with only the two reviewed hash values changed. A subsequent raw-byte format correction invalidated only the branch
audit pair; those two commands passed separately in 24.666s / 23.455s. Original
four-command receipts are preserved, and the interface pair was not repeated.

The original 2022 platform diagnostic remains FAIL (11.84s): immediate setters
verified, but saved state retained only Linked Original_A and did not prove
persisted divergent platform selections. The original 2024 GUI observation
remains BLOCKED (one skipped body, 224.27s): the owned window was identified,
but one directed click produced no observed image change. Neither is native
absence or generic completion; failed sandboxes/evidence remain retained.
Root's separate full Program on `e80d9250` remains pending at this handoff.
R41 staged controls are separate receipts in the test inventory, not an
aggregate gate. No merger pytest, native, Fresh or publication ran. Root owns
review and the next single 2025 Source acceptance attempt on the fixed stage.

## R42 Source-plugin selection, staged Voice and exact evidence requirements

Runtime merge `779823d3` combines exact accepted `8664cfb6`, `1a1b3b03` and
`bba85da9` from `e80d9250`; the separate #192 suffix/history candidate is not
included. Shared files retain clean component composition, with no merger
runtime fixups. Source selection now admits the closed AudioFileSource/Source
role union with independent class/catalog/direct-parent proof. The existing
linkage disclosure still promises neither unlinking nor platform isolation.

Root's original full Program on `e80d9250` ended **13,529 passed, 7 failed,
4 skipped in 5,044.89s**. The seven repaired nodes separately passed in
**8.74s**; the portable RTPC continuation follow-up passed **3 tests in 2.37s**,
including a Windows-shaped envelope on macOS, not native Windows evidence.
The original full result is retained and is not a final-candidate gate PASS.

On 2025.1.7.9143 macOS Console, Source-plugin A→B selection on `d64e0db7`
passed in **8.58s** (70 public calls, four previewed transactions, 170 native
archives), with independent active GUID change and retained-state proof.
Staged Voice creation then Source creation on its bound GUID on `1a1b3b03`
passed in **6.10s** (33 calls, two transactions, 86 archives), diagnostic-only.
Atomic planned Voice+Source language remains unresolved. The three original
atomic Source failures remain FAIL, with quarantined sandboxes; neither these
passes nor those failures grant whole-family, other-version or native-absence
credit. Source hash/mtime/tree remained unchanged and no owned process remained.

Four exact 2025 Media Pool return-option requirement rows retain both program
and native requirements. No capture/index entry or new coverage credit is added;
#195 population and missing native proof remain open. Four serial inventory
commands passed once (16.605s / 16.775s / 23.544s / 22.241s). All 153 Registry
machine seals, 272,313 native obligation rows and compressed obligation bytes
remain exact; requirements digest/source candidate and only reviewed public
contract references refresh. Source membership stays 79/91 indexed entries,
with 330 files in candidate closure. Policy formatting is unchanged apart from
the single approved operation-contract hash. No merger pytest/native/Fresh ran;
Root owns promotion and the next gate. No ticket is closed by this integration.

## R44 scoped Source, staged completion and exact Render/history integration

Runtime merge `f173d0c0` integrates only `4f869927`, `d8c55b4d` and `39b7cfc9`,
including exact-history `cb0e6b3d`. It preserves the observed legacy Tone
selection boundaries, the Gateway-owned two-Preview Voice/Source completion,
exact existing-GUID rename/notes/history, and complete Render identity/context
checks. Existing-GUID autosuffix branches remain excluded. The only manual
conflicts were additive test helpers/cases; all independent collector modes and
four version-build branches are retained.

The central preflight passed **826 tests in 51.09s**; the deduplicated
shared-conflict focus passed **7 tests in 25.30s**. The four serial inventory
commands passed once. Three reviewed aggregate seals refresh while all
272,313 native obligations, their compressed bytes, requirement/evidence policy
and source/index memberships remain intact. Exact results and original separate
native component receipts are recorded in [the test inventory](../../../tests/TEST_INVENTORY.md).

Render native acceptance, ordinary Source graphs, broader #192 work and final
#195 gates remain open. No native/Fresh run, push, main merge or ticket closure
was performed by this integration. Root owns review and publication.

## R46 existing Source preservation and Render collector integration

Runtime merge `5e41bed1` combines accepted `7979072d` and `dceb20f1` with no
conflicts; all 11 changed files retain exact component blobs. It adds ordinary
fail-mode Source placement under bound Sound/Voice owners, observed file/plugin
Source preservation through bounded pages, and the reviewed scoped Render
receipt-reference repair without changing global limits.

The deduplicated affected focus passed **9 tests in 27.44s**. Four inventory
generate/check commands passed once. One reviewed aggregate seal and four
`object.set` contract references refresh; all native obligations, compressed
bytes, owners and evidence requirements remain intact. Exact scope and original
2022 native PASS / 2025 capacity FAIL are recorded in
[the test inventory](../../../tests/TEST_INVENTORY.md); neither is regraded.

No local preflight or native/Fresh/full gate ran. Root owns review, publication,
exact-head hosted CI and one new 2025 Render sandbox acceptance attempt. Ordinary
Source native preservation, broader #192 and final #195 gates remain open.
