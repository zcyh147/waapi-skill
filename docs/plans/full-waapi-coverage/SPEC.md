# Eliminate Skill-origin WAAPI coverage gaps across Wwise 2021.1–2025.1

Date: 2026-10-17. Baseline: merged repair PR #173, commit `07c20232`.
Status: specification for review and subsequent ticket decomposition. No implementation or Fresh execution is authorized merely by publishing this specification.

## Problem Statement

Wwise supports valid operations, parameters and property conditions that the Skill sometimes rejects because its own wrapper is incomplete. Examples include unhandled `conditions`, missing parameter alternatives, and independent ShareSet placement omitted from an otherwise supported plugin-creation route. An API appearing in the catalog, or one example passing, does not mean all its valid uses are available.

The previous repair delivered known fixes and an indexed audit, but explicitly deferred additional gaps. That did not satisfy the user's request to generalize the fixes and eliminate the same failure class across the interface. The current audit proves reproducible accounting; its completion option reports incomplete unconditionally rather than determining whether the implementation and required evidence are complete.

## Solution

Follow one direct flow: obtain native API and metadata truth, compare it with the public Gateway, implement missing supported shapes and uses through the existing architecture, verify Skill routing, and test the outcomes. Cover all five supported release lines. Ordinary Authoring APIs previously excluded from the product are included, except the two explicitly excluded Authoring Lua/launch additions.

The deliverable is a usable interface with no remaining known in-scope rejection caused by missing Skill implementation. An inventory is a tool for achieving that result, not a substitute for it. Every new omission discovered during this effort remains implementation work within this effort.

## User Stories

1. As a Wwise user, I want every in-scope native capability available through the Skill, so that wrapper omissions do not block legitimate work.
2. As a user of Wwise 2021.1, I want my version examined directly, so that newer-version behavior is not assumed to apply.
3. As a user of Wwise 2022.1–2025.1, I want each release line independently accounted for, so that version differences are implemented correctly.
4. As an Authoring user, I want ordinary layout, view, window, model and signal capabilities included, so that the old Console-centered subset does not define my available functionality.
5. As a user, I want previously collected native evidence reused when sufficient, so that the investigation does not repeatedly collect the same material.
6. As a user, I want missing schemas collected from the matching host and version, so that the Skill does not infer their shape from API names.
7. As a user, I want every permitted parameter and option expressible through a business interface, so that a complex native structure does not become an unsupported feature.
8. As a user, I want legal enum choices and their meanings disclosed, so that I do not have to guess native values.
9. As a user, I want omitted values, explicit defaults, empty values and nullable values handled correctly where legal, so that the wrapper preserves native semantics.
10. As a user, I want nested objects, repeated rows and alternative input shapes supported, so that only simple examples are not favored.
11. As a user, I want valid property conditions handled across object classes, so that the fix is not limited to one attenuation or GameParameter example.
12. As a user, I want required prerequisite changes visible in the Preview, so that the Gateway does not silently change unrelated settings.
13. As a user, I want incompatible, cyclic or ambiguous requirements explained accurately, so that genuine invalid requests remain distinguishable from missing implementation.
14. As a user, I want new-object configuration to respect available class metadata and native defaults, so that fields are not rejected merely because the object does not exist yet.
15. As a user, I want a supported staged workflow when native creation cannot express the whole result in one call, so that partial progress can finish without duplicate objects or hidden writes.
16. As a plugin user, I want applicable live properties and references discovered rather than a small hard-coded subset, so that plugin fields remain usable through the same interface.
17. As a user, I want owner-local effects, independent ShareSets and Source plugins treated as separate uses, so that one successful creation mode does not conceal another omission.
18. As a user, I want valid target types, parent placements and create/edit/conflict modes checked separately, so that an existing API name does not overstate support.
19. As a user, I want complete permitted query and metadata projections, so that retrieving required details does not require invented commands.
20. As a monitoring user, I want valid Topic filtering, event shapes and termination behavior handled, so that successful subscription setup is not confused with receiving the requested events.
21. As an import or build user, I want valid file rows, replacement modes and build options preserved, so that successful invocation corresponds to the intended output.
22. As a runtime or UI user, I want correct-host execution and appropriate effect verification, so that a returned success is not mistaken for an unobserved outcome.
23. As an Agent, I want the Skill to lead to the correct Gateway route and complete schema, so that I can perform the task without repository research or native request synthesis.
24. As an Agent, I want invalid-field errors to identify the field and permitted alternatives when known, so that a recoverable mistake has an actionable next step.
25. As a user, I want the three existing modification policies, configuration binding and execute-once rules retained, so that broader coverage does not weaken authorization.
26. As a user, I want unknown write outcomes diagnosed without replaying the original write, so that additional coverage does not duplicate changes.
27. As a maintainer, I want every native branch linked to its public input, implementation and required evidence, so that omissions cannot hide behind a family-level completion label.
28. As a maintainer, I want deleting a branch, enum choice, version or required proof to fail the completion check, so that coverage cannot regress silently.
29. As a maintainer, I want implementation gaps, native limitations and unavailable test environments distinguished, so that unsupported labels do not conceal unfinished work.
30. As a user paying for Agent tests, I want deterministic validation to carry most coverage, so that Fresh testing remains small and useful.
31. As a user, I want every newly discovered omission assigned implementation work, so that investigation cannot end by moving the problem outside the agreed scope.
32. As a user, I want the overall effort kept incomplete while required branches or evidence remain missing, so that a completed audit is never presented as a completed product.

## Implementation Decisions

### 1. Establish the complete native input set

- Cover Wwise `2021.1`, `2022.1`, `2023.1`, `2024.1` and `2025.1`. Record exact collection builds and hosts; do not extrapolate tested builds to every historical or future patch release. Detect drift and reconcile changed shapes before claiming compatibility.
- Include functions and Topics on their correct host, ordinary Authoring additions, and the currently permitted runtime capabilities. The present packaged profile is an implementation to compare, not the authoritative denominator.
- Reuse complete, version-matched historical reflection where provenance is sufficient. URI equality does not establish schema equality, and schema equality does not establish execution behavior.
- Obtain missing function/Topic lists, schemas and referenced definitions through controlled read-only reflection. Supplement API schemas with live object/class/plugin property, reference, type and condition metadata where those APIs expose extensible fields. Consult matching primary documentation when reflection does not specify meaning.
- All five historical Authoring URI lists exist. At least 48 known ordinary Authoring version/schema rows are missing from the inspected retained schema material: 23 for 2024.1 and 25 for 2025.1. This is an initial collection set, not a ceiling on discovered work. Shared Console/Authoring shapes without adequate evidence also remain collection or comparison obligations.
- Opening matching Authoring versions sequentially for necessary reflection is authorized. Use owned disposable projects and the established lifecycle; preserve user work. Keep configuration-only live connections and validate actual host/version/build. Repair stale developer collection paths without restoring public connection overrides or broadening a narrow direct-client exception.

### 2. Compare real branches, not only API names

- Give each native field, enum alternative, union alternative, collection shape, optional/default distinction and referenced definition an exact version/host identity. Resolve reference reachability and retain result alternatives as well as input alternatives.
- Add meaningful business distinctions that API schemas alone do not encode: target type, parent placement, create/edit mode, plugin topology, platform applicability, prerequisites and resource lifetime.
- Map each relevant distinction to a public Business Declaration or fixed read/Topic contract, construction and validation behavior, route discovery, verifier and required test evidence. A whole-module pointer or a parent schema mapping does not establish every descendant's support.
- Deduplicate genuinely equivalent branches using explicit semantic and version evidence. Do not multiply arbitrary scalar values into an infinite test space, but do not merge distinct business modes merely because they share a URI or implementation family.
- Use independent native sources as the comparison input; generating both expected coverage and implementation claims from the same registry is insufficient.

### 3. Generalize missing implementation through existing boundaries

- Preserve Gateway-Owned Request Construction and the accepted Business Declaration architecture. Reuse Operation Drafts, Field Handles, immutable Change Previews, authorization, execution and verification. Do not add a raw payload escape hatch or a second execution framework.
- Implement the complete observed valid metadata-condition vocabulary across the five lanes, with semantics for applicability, relationships and prerequisites established from native sources. Replace one-object special cases with reusable handling where the semantics are shared.
- Reject genuinely conflicting, cyclic, malformed or unsupported-by-native expressions accurately. A valid observed expression that the Skill cannot yet handle remains an implementation gap and blocks coverage completion; it is not a satisfactory permanent boundary.
- For new objects, use validated class/default facts when sufficient. Otherwise provide an explicit supported staged workflow, with separately authorized Previews and independent readback, retaining verified identity and never silently recreating the object.
- Fill missing permitted fields, enums, optional modes, nested shapes and repeated structures in the existing version-aware contracts and materializers. Values remain business-facing or Gateway-disclosed scoped handles; the Agent never constructs native requests.
- Support all in-scope ordinary Authoring additions through the same interface principles, with actual host detection and appropriate resource ownership. Retained command catalogs are snapshots; instance-dependent availability still requires live discovery.
- Apply the same review to imports/builds, runtime controls, fixed reads, Topics, zero-input operations and result validation. Input simplicity is not an exemption from complete routing and outcome handling.
- Investigate existing packaged boundaries rather than inheriting them as native limitations. In particular, the failed single encoding of classic 2021 ShareSet creation does not prove all native alternatives impossible.

### 4. Make the supported capability reachable to an Agent

- Keep the main Skill instructions concise. They must route each task family to discoverable Gateway operations and schemas; they need not enumerate every API or field in prose.
- Verify compact directories, detailed schemas and continuations together. A capability is not delivered if its builder exists but the public schema omits it, or if the advertised continuation cannot reach it.
- Disclose legal choices and material dependencies before submission. Invalid input should identify the affected field and known alternatives without inventing meanings.
- Preserve bounded output with complete pagination or structured continuation where appropriate. A resource ceiling is not a Wwise capability limit and must not silently remove supported fields.
- Keep configuration-only connection identity, host/version checks, the three modification policies, execute-once behavior, uncertainty reporting and required cleanup. Scope expansion grants no direct-client or arbitrary-code bypass.

### 5. Make completion evidence-driven

- Track at least: unresolved, missing implementation, implemented but missing required evidence, blocked by environment, verified, proven native absence, and explicitly approved exclusion. Missing Skill support must never be classified as native absence.
- Completion is computed from exact mappings, reachable public contracts and required evidence, not a fixed incomplete flag, a declared family status or a test-definition filename. Reproducibility and functional coverage are separate results.
- Maintain a per-branch evidence requirement: deterministic public-interface proof for every applicable lane; native evidence where effects, metadata semantics or version/host behavior need it; Fresh only for selected interaction mechanisms. Existing evidence may be reused only when its relevant source, native shape, host and behavior are demonstrably unchanged.
- An explicit native observation limitation may require a truthfully weaker public result. Missing Skill verifier implementation is not such a limitation and remains work. Never claim verified business state from a schema-only success.
- An execution profile's count includes only correctly classified rows. Approved exclusions and proven native absence remain visible but are not successful execution credit. An API's absence does not by itself prove the requested business outcome has no supported alternative.
- Every discovered in-scope gap receives a linked implementation/evidence obligation before the discovery task closes. Investigation milestones may finish; the implementation parent cannot close while any such obligation remains unresolved.
- No new ordinary capability may be excluded merely because implementation, test setup or verification is difficult. Broader exclusions require a new user decision. Missing environments/licenses remain blockers, not passes.
- Final completion requires all in-scope branches resolved, all required gates satisfied, reviewed source/evidence seals reconciled, and no open obligation hidden in a deferred list. Incremental merging does not change that condition.

## Testing Decisions

- Use the existing public Gateway parser and execution entrypoint as the primary seam. Drive real public schemas, continuations and requests with injected native clients and isolated configuration/state; assert observable outputs, exact native dispatch and absence of unintended effects. Internal helper tests supplement this seam rather than substituting for it.
- Prior art includes the current metadata list/detail/change chain, five-version configuration-binding tests, GameParameter class-field and staged-workflow tests, independent ShareSet topology tests, policy recovery tests and authenticated query-refinement archive tests.
- Cover every applicable five-version contract lane with positives and meaningful invalid-input controls. Include defaults versus omission, nested/union alternatives, applicable targets, version/host mismatches, stale handles, dependency conflicts and partial outcomes. Do not use implementation-mirroring assertions as the sole proof.
- Test the completeness checker by removing a route, legal field/enum/union branch, applicable version, mapping or required evidence; substituting a URI at unchanged count; misclassifying missing implementation as native absence; and attributing parent/family PASS to an unproven leaf. Every such corruption must prevent completion.
- Run focused tests while implementing, then the established full five-version Program and full Non-live gates on the combined candidate. Rerun affected gates after material changes; preserve exact candidate attribution instead of relabeling historical counts.
- Run deterministic real Wwise validation sequentially in the existing owned sandbox lifecycle. Prove the business effect and preservation appropriate to the API, including real event delivery/resource cleanup where relevant. Use matching versions/hosts for native differences and record explicit proof for any proposed equivalence-based reuse.
- Separate reflection, fake-client proof and real execution evidence. Reflection alone proves neither a usable Gateway wrapper nor a successful business outcome.
- Before spending Fresh quota, prove the actual producer-to-Gateway-to-Broker-to-grader-to-archive chain deterministically, including legal argument forms, generated continuations, legitimate refinement and safely rejected commands. A harness must not prohibit a valid public path merely because its first fixture used another spelling.
- Use only the existing formal Fresh Codex campaign/matrix harness. Fresh is Mac-only, selected by distinct routing/interaction mechanisms rather than every API multiplied by every version. Propose exact cases, turns, transactions and maximum attempts before launch. Preserve the established Terra / medium / default baseline unless separately changed; this specification authorizes no Fresh run or automatic retry.
- Freeze code/options during each Fresh batch; retain raw failures, stop on systemic evidence/cleanup faults, and replay only originally all-PASS roots with identical verify-only options. Record cumulative evidence honestly. Windows-shaped program tests are not native-Windows execution evidence.
- At handoff, report unresolved obligations as unresolved. Do not lower the success criterion to make the current ledger pass.

## Out of Scope

- Adding the two previously excluded Authoring interfaces `ak.wwise.ui.cli.executeLuaScript` and `ak.wwise.ui.cli.launch`. Existing public Core/CLI Lua behavior remains unchanged in scope.
- Removing approved dangerous-field protections, opening raw native requests/direct clients to the Agent, or bypassing configuration and modification policies. Existing restrictions must be traceable, not expanded to conceal omissions.
- Wwise release lines outside 2021.1–2025.1, speculative future API shapes, and claims of compatibility with unexamined patch/build changes.
- Exhaustively enumerating arbitrary numeric values, every possible project graph or every future third-party plugin. This does not exclude supported parameter alternatives, observed condition grammars, applicable business modes or reusable live-metadata handling. Required evidence unavailable because of a missing plugin/license remains an explicit blocker for the affected in-scope branch.
- A full Fresh cross-version/per-API matrix or unapproved Agent reruns. This is a cost boundary on the test method, not permission to leave functional coverage incomplete.
- Changes to user production projects, replay of historical uncertain transactions, or deletion/regrading of historical failure evidence.

All remaining discovered omissions in the agreed native/business scope are implementation work under this specification, including gaps beyond the initial audit groups or 48 known missing Authoring schema rows.

## Further Notes

The user confirmed the direct reflection → comparison → wrapper completion → Skill routing → verification workflow. The public Gateway test seam and cost-controlled testing ladder continue the already agreed plan; no new test framework is proposed.

Historical Authoring inventories exist for all five versions, but full independent Authoring schema sets were not found in the inspected roots. The initial history review and wayfinder checkpoint are supporting evidence, not completion claims. Current structural counts contain duplicated version/profile occurrences and shared definitions, not an equivalent number of separate bugs.

Previous PR #173 remains a completed known-repair delivery. This specification restores the broader requested outcome and supersedes its deferral allowance for newly discovered in-scope gaps. The next phase is English implementation tickets with native blocking links, organized around reusable mechanisms and concrete business completion. Each ticket must retain its branch identities, version obligations, public-route tests and required outcome proof.

## Execution detail — 2026-10-23

Execution follows the [shared test-selection and evidence-reuse rules](https://github.com/zcyh147/waapi-skill/blob/codex/full-waapi-coverage/tests/semantic/TEST_ACCEPTANCE.md). Scope and existing dependencies remain unchanged.

Retain all 21 tickets, native dependency edges and the full 2021.1–2025.1 scope. Organize affected tests by shared implementation, with independent case outcomes and isolated state. Preserve valid historical evidence and distinguish business failures from report/evidence-tool failures. Required full gates run on settled integration batches; Fresh remains separately budgeted. Material increases in verification depth or cost require the user's decision before implementation. No unresolved omission is removed from this parent by these scheduling changes.

## User-approved evidence method — 2026-10-24

The user selected risk-based native validation. All in-scope APIs, parameters,
branches and five-version public program coverage remain required. Real Wwise
validation must establish relevant nonempty data, business meaning, version/host
differences, source preservation and cleanup. It need not manufacture every
boolean value or repeated collection shape on every lane merely to demonstrate
deterministic result preservation already covered by public program tests.

Apply this decision through an exact, independently reviewed requirement mapping.
Keep every branch identity and owner visible, explain each changed evidence
requirement, and retain the native availability and semantic obligations that
support program-only preservation claims. Missing wrappers, unobserved business
effects, unexplained native differences and incomplete cleanup remain unfinished.
Do not rewrite historical requirements, results or failures; record the successor
policy and its current evaluation separately. This decision authorizes no Fresh
attempt, native absence claim or capability exclusion.

## User-approved explicit media choice — 2026-10-24

The user approved one precise input boundary: for Wwise 2023.1
`ak.wwise.core.transport.useOriginals`, the Agent must explicitly choose
`originals` or `converted`. Both choices remain fully supported. The reflected
2023 argument schema permits omitting `enable`, but the matching API, argument
and example documentation does not define the omitted behavior. Do not guess a
default or expose an opaque native-default choice.

This exception covers exactly four existing branch IDs: Console and Authoring
build 2023.1.19.8928, each with `/argsSchema/@empty/object` and
`/argsSchema/properties/enable/@presence/absent`. Preserve their identities and
schema-admitted classification. Verify explicit public rejection without target
dispatch, the same-operation valid choice, and the existing native route gates.
Record them as the approved explicit-choice boundary, not successful native
omission, native absence or an invalid native schema. Historical failures remain
unchanged. Every other version, branch and unresolved capability stays in scope.


## User-approved prerequisite and delivery batches — 2026-10-25

Implement [#197](https://github.com/zcyh147/waapi-skill/issues/197) before
resuming business-feature work. Retrospect the main task and relevant subagent
incidents, deduplicate causes, repair confirmed framework gaps, and exercise
batch selection, failed/affected reruns, durable results and relevant evidence
reuse through the existing test entrypoints. Existing verified fixes and new
fixes must be counted separately; measured time must not be presented as a
complete accounting of unmeasured elapsed hours.

The published child split and native dependency edges are recorded in
[delivery-batches.json](delivery-batches.json): #198–201 partition #186 and
#202–204 partition #193. Original canonical owners, branch identities, scope
and historical outcomes remain intact. Each child retains every applicable
2021.1–2025.1 obligation and can be accepted independently of unrelated children.
No obligation is completed or excluded merely by splitting a ticket.

Group compatible object/property, media/file, runtime/event and Authoring
tests while isolating mutable state and preserving independent outcomes. Use
Python program tests plus proportional real-Wwise effects for functional work.
Centralize separately budgeted Mac Fresh interaction testing in #194; #195
aggregates its results and coordinates the required final combined gates,
without a duplicate Fresh campaign or per-ticket full-repository sweeps.

**Mandatory stopping point:** after #197 is implemented, reviewed, integrated
and accepted, pause the existing Goal and report the unique problems found,
already-fixed problems, newly fixed and regression-proven problems, remaining
problems and the evidence-backed causes of repeated attempts. Do not start
downstream business work until a new user instruction. No Fresh is authorized
for #197. Preserve original evidence and avoid additional verification-depth
expansion without the existing required user decision.

## User-approved internal Debug verification boundary — 2026-10-26

`ak.wwise.debug.getWalTree` and `ak.wwise.debug.validateCall` retain their
existing closed wrappers. The user instructed that further verification and
Debug-environment work be skipped. New real Debug execution is therefore not
required for #203, #193 or #174 closure. Preserve existing program proof and
the explicit current-host unavailable behavior; claim neither native execution
nor native availability. This exception changes no other API obligation or
historical result. Removing these routes from normal discovery is not part of
this change.

## User-approved Tone file-creation outcome — 2026-10-26

For #202, `ak.wwise.debug.generateToneWAV` must construct the correct closed,
versioned call and establish that the exact owned output file was created or
observably rewritten. The user explicitly excluded file-internal quality
assurance: headers, channels, rate, markers, waveform mathematics, noise,
envelopes and audibility are not acceptance requirements. This supersedes the
previous Tone content-verification obligations, including their partial-result
completion barriers; historical receipts and verdicts remain unchanged.

Keep legitimate parameter construction and native version/host boundaries,
configuration-only connections, the three modification policies, immutable
Preview, one execution, owned output confinement, stale-file and drift checks,
source preservation and cleanup. Public verification states its
`file_creation_only` scope and `tone_file_creation` strength, without certifying
file contents or audio quality. Retained WAVs and matching native creation
receipts may be reused; no new Wwise or Fresh run is required merely to refresh
that proof. Existing nonnegative marker-position and embedded-NUL guards remain
disclosed Gateway input constraints, not claims that Wwise rejects these values.
