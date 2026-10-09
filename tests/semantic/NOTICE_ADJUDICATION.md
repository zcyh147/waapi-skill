# Limited notice adjudication and development gates

## Current prospective checkpoint — v6, #147

New plans use `waapi-skill.expansion-notice-adjudication/v6`. V6 keeps v5's
input/evidence semantics and High/default reviewer settings, clarifying only
ordinary future verification intent: saying preservation will be checked after
execution does not assert prior discovery/acquisition, guaranteed proof or a
stronger transaction verifier. Missing exact pre-Execute follow-up discovery
alone is not an unsupported-follow-up finding. Actual public reads still obey
discovery requirements. Explicit unsupported methods, false capability,
completed/guaranteed proof, verifier overclaims, uncertain edit scope, false
baselines and all timing/authorization/provenance/non-PASS gates retain their
boundaries. Terminal proof cannot come from future intent or after-state rescue.

V1–v5 retain exact rubric/configuration digests, settings and sealed replay;
v5 remains High. The schema, 120-second bound, isolation and input/output
ceilings remain fixed. Compact C09 contrasts and fake runner/archive checks
prove input transport, invocation binding and read-only replay/tamper rejection;
they do not prove language accuracy or semantic acceptance. Historical roots
remain frozen without rejudgment. Combined development gates and new Fresh
failed-only C09 acceptance are separate coordinator-owned work.

## Approved amendment — 2026-10-08

Read this contract when implementing, reviewing, running or replaying the
integration-expansion notice adjudication path. The user approved limited
independent Agent review of natural-language notices the deterministic parser
cannot decide. The [#147 amendment](https://github.com/zcyh147/waapi-skill/issues/147)
supersedes only its former no-model-grader restriction. This document records
the approved development contract. The implementation checkpoint below records
its current developer proof and pending acceptance separately.

The normal Skill/product interaction, business prompts, independent business
oracles and Gateway runtime remain unchanged. Reuse the existing formal Fresh
campaign/matrix and Codex subprocess infrastructure for the optional review
stage; the executing Agent cannot grade itself.

## Decision and reviewer boundary

The harness must distinguish deterministic acceptance, material rejection and
review-required notice evidence. A parser's unsupported expression is not itself
a demonstrated contradiction, and review-required is not PASS. The copied c914
witness must enter review-required rather than automatic acceptance.

Deterministic checks retain authority over actual grants and confirmation,
identities, immutable prepared operations, notice/execution phase order,
executed values, extra writes, preservation, Gateway verifier strength and
evidence integrity. A positively established material failure cannot be rescued
by a reviewer. Correct target/effect/value and visible prospective meaning are
mandatory. Baseline bookkeeping prose is optional; when supplied, concrete
baseline owners, counts and values must agree with sealed facts. Auxiliary
read-summary wording neither proves the edit nor grants authorization.

For review-required evidence, submit one complete relevant visible pre-execution
notice, referenced earlier visible context, original event positions, sealed
before-state, immutable prepared operation and independently attested roles.
Bind the input to its exact transaction, Preview and timeline. The isolated
reviewer receives no after-state, business verdict, successful Execute result,
credentials, executing-Agent memory or Gateway/Broker mutation access. Business
success cannot supply missing notice meaning.

Use one bounded review with pinned model, reasoning effort, service tier and
rubric. A complete schema-valid judgment must ground its reasoning in notice
text and obligations. Missing, malformed, truncated, timed-out, unavailable,
conflicting, ambiguous or unresolved judgment remains non-PASS. Review does not
permit an execution retry, repeated votes until acceptance, or a second business
execution harness. Measure reviewer time/cost separately from executing-Agent
duration.

## Provenance and replay

Seal exact reviewer inputs/output, decision, text/obligation references,
transaction/Preview/timeline bindings and effective reviewer configuration,
including prompt/contract and runtime identity hashes. Prove tamper rejection
through the actual runner/archive path. An identical successful-root
`--resume --verify-only` validates the sealed receipt and bindings without
model rejudgment, Wwise invocation or grade writes. Replay proves the preserved
judgment and its provenance; it does not reproduce a stochastic judgment.

Apply the new contract only to new frozen runs. Historical FAILs, quarantines,
legacy grades and original negative fixtures remain immutable. Named versioned
tests and an explicit semantic rationale own prospective expectation changes.
Retain legacy deterministic replay behavior for legacy records.

Both review admission paths use Gateway-owned `validate_transaction_id`: compact
IDs contain exactly 20 lowercase Crockford Base32 characters after `tx1-`; safe
legacy IDs retain the public Gateway contract. Identity is never coerced or
normalized. Exact transaction, Preview and timeline bindings remain mandatory.

## Bounded implementation and dependencies

| Ticket | Parent / dependency | Completion boundary |
| --- | --- | --- |
| [#157 readiness](https://github.com/zcyh147/waapi-skill/issues/157) | #108; no blocker | Reuse existing launch/preflight seams to reject missing interpreter, applicable config, fixture/media or conflicting process prerequisites before expensive child launch. Program-only lanes acquire no unrelated live prerequisites. Readiness performs no installation, hydration, config edits, process kills or project changes. |
| [#158 fast notice feedback](https://github.com/zcyh147/waapi-skill/issues/158) | #108; no blocker | One deterministic bounded Poetry-backed selection of notice and fake runner/archive regressions, with non-live flags, authoritative exit status and nonempty collection. No model/Wwise launch. #158 owns the fixed command and its README usage. |
| [#159 C09 review path](https://github.com/zcyh147/waapi-skill/issues/159) | #147; no blocker | One end-to-end effect-append decision, isolated review, receipt and replay path. Prove hard-failure nonoverride, uncertainty, malformed/timeout handling and tampering with real-function fixtures and fake runner/archive tests. Activation stays limited to the approved new C09 contract. |
| [#160 remaining workflows](https://github.com/zcyh147/waapi-skill/issues/160) | #147; blocked by #159 | Extend the reviewed path to selected import/media, RTPC, attenuation, music and Stinger contexts with exact roles, quantities, order and preservation. Retain later human confirmation in ask mode and separate durable authorization in allow mode. Notice review cannot upgrade attenuation's schema-only verification. |

Schedule the tooling improvements first, then #159/#160. #157/#158 are not
artificial technical blockers for #159. These approved new packages do not
retrospectively split completed repairs; #147 remains the consolidated owner.

## Cheap feedback to complete acceptance

1. Check applicable prerequisites with existing readiness/launch methods. Use
   affected functions, copied exact witnesses, independent contrasts and held-out
   compositions during implementation. Prove actual Gateway-generated-to-consumed
   chains where changed; separate ordinary Poetry pytest from Skill-local Fresh.
2. Complete bounded independent Standards/Spec review and fake runner/archive
   proof, including verify-only with no model invocation. Classify material
   notice, unsupported-language judgment, reviewer infrastructure, provenance,
   Agent execution and business failures before repair or rerun.
3. Freeze the reviewed combined candidate and complete the required development
   gates once at promotion, including full Non-live for this substantial harness
   contract. Focused feedback is not full Non-live or semantic acceptance. Repeat
   broad gates when changes or failures invalidate their evidence.
4. Coordinate new targeted EXP25-C09 proof and identical successful-root audit
   under #147. Report whether the fallback actually ran; supported wording does
   not prove adjudication. Freeze every FAIL root without replay or regrading.
5. [#122](https://github.com/zcyh147/waapi-skill/issues/122) retains final full
   macOS acceptance of one frozen candidate: all 13 positive Agent units plus
   the separate EXP22-M05 capability boundary, identical successful-root
   verify-only, final independent integration review and accurate reporting.
   Failure-first scheduling in `tests/AGENTS.md` does not waive that complete gate.

For delegated work, every spawn explicitly uses `fork_turns="none"`. Supply
only the objective, constraints, acceptance, essential decisions and source
pointers; require the same recursively. Use GPT-6.1 Sol Medium for bounded
execution and High for difficult design/review. Preserve historical model pins
and separately seal executing/reviewer settings in new runs.

## Retrospective basis and limits

The 2026-10-07 15:59:59–2026-10-08 00:50:40 Asia/Shanghai audit recorded eight
complete Non-live runs (115.87 minutes), eight scoped Fresh matrices (14.53
minutes) and linked focused runs (at least 4.62 minutes): 25.44% of the
8h50m41s window. The remainder is unallocated chronology, not measured thinking
or review time. All eight Fresh units retained notice-only FAIL with six passing
independent business assertions. Consolidate decision/repair families before
promotion; these measurements create no PASS credit or promised savings.

Durable local authorization, cost tables and framework analysis are preserved
outside the tracked tree at
`/Users/xiye/Documents/Git/waapi-skills/.waapi-skill-state/evidence/waapi-test-remediation/retro-20261008/`:
`waapi-notice-adjudication-authorization-20261008.md`,
`waapi-eight-hour-cost-audit-20261008.md` (and JSON/metadata), and
`waapi-framework-ticket-retro-20261008.md`. Broad AGENTS/checkpoint
reorganization remains deferred; this amendment preserves all historical counts.


## C09 implementation checkpoint — #159

New expansion C09 task plans pin `waapi-skill.c09-notice-adjudication/v1`, the
reviewer settings and runtime identity hashes. Legacy plans retain the original
boolean notice parser and replay. The copied c914 notice in
`tests/fixtures/semantic/c09-notice-adjudication-v1.json` is a prospective
contract fixture: its legacy judgment remains FAIL, and its new decision is
review-required until an independent valid judgment exists.

`codex_c09_notice_adjudication.py` keeps the new C09 decision, isolated review
and receipt validation together. Existing role attestation and timeline
extraction establish the immutable request and notice phase. Deterministic
acceptance is preserved; structural failures and a small set of exact affirmative
material claims reject. Other unsupported wording enters review-required. The
reviewer cannot run unless every other task gate passes. The existing Broker,
transaction policy and independent business oracle retain their authority.

The reviewer uses the existing Codex command builder, disposable environment,
prompt audit and process-group infrastructure, in an empty temporary workspace
with no injected Skill, Broker overlay or project capability. The fixed settings
are `gpt-6.1-sol`, medium reasoning and default service tier. Its total deadline
is 120 seconds; input is at most 128 KiB, each subprocess output is at most
512 KiB, and the final judgment is at most 16 KiB. CLI capability probes and one
prompt audit precede exactly one ephemeral review turn. There are no retries.
The reviewer receives the original user prompt, all visible messages before the
first Execute, original event positions, before-state, immutable prepared
operation and attested roles. Raw post-Execute events, after-state, business
verdicts and execution receipts are excluded. Transaction, Preview and the
pre-execution timeline hashes bind this input. Reviewer seconds and token usage
are recorded independently of executing-Agent seconds; no monetary cost is
inferred from tokens.

The supported disabled-feature flags are attested from the selected CLI's
`features list` and `exec --help`. These flags and the prompt audit do not prove
a complete absent-tool inventory: CLI 0.159.2 does not expose that inventory.
Any observed tool use or incomplete session fails the judgment. Read-only
sandboxing, supplied capability removal and event auditing are the implemented
controls, not a claim of complete security isolation against a hostile CLI.
No credentials are included in reviewer input; model authentication remains
inside the disposable Codex environment.

The CLI may disclose its bundled system Skill catalog under its own disposable
`CODEX_HOME/skills/.system`; this differs from injecting a user or WAAPI Skill.
New invocation bindings use `waapi-skill.c09-review-invocation/v2` and seal the
audit process's canonical `CODEX_HOME` before any subprocess launch. Both live
audit and replay classify bundled entries only below that independently bound
root, using the existing ownership-aware inventory audit. A prompt's advertised
root cannot authorize itself. User/WAAPI Skills, memory and changed developer
instructions still reject before the review turn. Replay compares traversal-free
archived absolute identities without resolving or looking up the deleted
temporary root. V1 bindings retain their historical audit semantics; original
FAIL roots remain frozen.

Before subprocess launch, a separate harness-owned invocation binding records
fixed configuration/runtime, the decision digest, sealed temporary host locators
and exact schema text. Its digest is stored separately in the task turn record.
The existing archive verifier reconstructs both canonical commands using fixed
settings and those locators, and requires exact argv equality. Duplicate settings,
conflicting feature overrides and changed schema operands cannot be accepted by
token membership. Neither command expectations nor configuration are selected
from the reviewer receipt. Rewriting the binding and receipt checksums cannot
replace the turn's independently sealed binding digest.

The capped subprocess path retains bounded original stdout/stderr bytes as
base64 and decodes them strictly. Invalid UTF-8 records an explicit non-PASS
status plus a decoding diagnostic; it cannot be deleted or repaired into an
accepted judgment. The native child exit status remains distinct, and process
cleanup still completes. Successful replay validates original bytes against the
recorded text before judging. The legacy uncapped subprocess contract is unchanged.

The existing archive verifier also validates the exact receipt, configuration,
runtime hashes, grounded text references and source bindings.
It makes no reviewer or Wwise call and writes no grades. This introduces the
preserved independent model judgment as a new evidence authority. Replay proves
that judgment was preserved and bound; it does not deterministically recompute
its semantic truth. The campaign seal and trusted root remain prerequisites.
Receipt checks do not defend against an owner rewriting the entire trusted root.
Missing or substituted standalone judgment JSON cannot override a deterministic
failure or replace the recorded isolated invocation.

`test_codex_c09_notice_adjudication.py` exercises the decision, fake subprocess
review, existing task gate and complete real-TransactionStore archive paths,
including uncertainty, malformed/truncated output, timeouts, tools, hard
failures and tampering. It is included in the fixed `notice-fast` selection.
These are developer tests, not Fresh or Wwise acceptance. Independent review,
combined-candidate development gates, targeted Fresh fallback proof and identical
successful-root verify-only remain pending at this paused checkpoint. #160 and
broader adapter activation remain outside this implementation.

## Expansion workflow implementation checkpoint — #160

New task plans pin `waapi-skill.expansion-notice-adjudication/v1` for C01,
C03, C06, C08, C09, M01 and M05/2025.1. M05/2022.1 remains the separate
capability boundary. Plans without adjudication retain their original parser;
C09 plans pinned to the original C09/v1 contract retain that decision and
replay path. Original business prompts, independent oracles, fixtures and
product runtime are unchanged. The new contract and rubric hashes are sealed
in the plan, and the existing campaign semantic-tree fingerprint includes the
new Adapter source and fixtures.

`codex_expansion_notice_adjudication.py` owns the operation-specific Adapter
contexts. Before any positive decision or review admission, the existing case
Preview approver and typed role attestations must agree with the independent
before-state. Imports additionally compare prepared source snapshots, exact
source language/owner identities, target pre-state identities, file proofs and
music parent anchors. C06 reuses the sealed existing-association, before/delta
and ordered-point attestation; C08 reuses exact target/dispatch/curve binding;
C09 and M05 reuse the existing owner/reference attestations. New object roles
in M01 are typed creation destinations, never invented GUIDs. Numeric units
belong to their field: Track Volume and curve y are decibels, RTPC x is a
GameParameter value, and attenuation x uses the sealed distance domain without
assuming a unit conversion. M05 display labels may derive from associations;
its oracle preserves identity and real settings rather than literal display
name/path.

The preserved C08 source must independently prove a canonical GUID, Attenuation
type, name and path distinct from the edited copy. Equality of malformed
before/after source objects is not identity evidence; a missing, malformed or
aliased source is rejected before review, even if the existing business
equality oracle would agree.

The historical import notice parser only matches lexical groups. A match
cannot decide complete media mappings, property owners, extra writes or scope.
New C01/C03/M01 notices therefore generally require independent review after
typed attestation, with reason
`legacy-lexical-match-insufficient-for-complete-import-mappings-and-scope`.
The contextual legacy parsers likewise prove only selected edit frames; a
positive does not establish every supplied baseline, scope or verifier claim
in the complete notice. New C06/C08/C09/M05 notices also require complete
independent review, with reason
`legacy-partial-parser-insufficient-for-complete-notice-meaning`. Structural
hard checks and the existing C09 exact material-rejection checks remain
authoritative. The original C09/v1 default keeps its historical positive
shortcut; only the prospective contract opts out of that shortcut. Supported
or unsupported wording is never automatic PASS under the new contract.
Narrative order may differ when the exact
mapping and curve point/shape meaning is clear; preservation need not use a
verbatim or exhaustive bookkeeping list. Missing or ambiguous edit meaning
remains non-PASS. The frozen independent contrasts have a separate source
provenance and do not redefine parser vocabulary or historical fixture grades.

All contexts reuse the same #159 isolated Codex invocation, fixed settings,
limits, strict original UTF-8 bytes, independently sealed invocation binding,
receipt validator and archive verifier. The extra rubric describes per-case
roles, quantities, field ownership and preservation. It receives neither
after-state nor business verdict. Ask-mode review applies to the first-turn
proposal; the later user confirmation, exact token and second-turn Execute
remain mandatory. Allow-mode review cannot supply the separate durable grant.
Attenuation keeps `result_schema_checked` Gateway strength and its separate
independent curve oracle. CLI feature pins and absence of observed tool events
still do not prove a complete hidden-tool inventory is absent.

`test_codex_expansion_notice_adjudication.py` is included in `notice-fast`.
It exercises all 13 positive version units through the real TransactionStore,
runner notice gate, fake isolated subprocess and complete archive verifier,
including both confirmation workflows. Independently grounded held-out
contrasts, uncertain judgments, reviewer timeout/malformed output, missing
notices, mismatched prepared roles, receipt substitution and authority
substitution remain failed or rejected on read-only replay without any model
call or grade write. These are fake developer proofs, not Wwise/Fresh or model
semantic acceptance. The evidence itself classifies deterministic material
failure, unsupported-language judgment, reviewer infrastructure and provenance;
execution/authorization and business outcomes retain their independent gates.
Combined independent review, frozen-candidate broad development gates and
final #147/#122 acceptance remain separate pending promotion work.

The #160 review repairs specifically reproduce the previously admitted C08
verifier/audibility overclaim beside a supported notice, false baseline claims
beside supported C06/C09/M05 notices, and an unattested C08 preserved source.
Complete review decisions and deterministic role rejection replay through the
same full runner/archive seam. No new wording blacklist or language grammar
was added, and the frozen legacy fixtures and oracles remain unchanged.

## Business notice obligations checkpoint — reopened #147

New plans use `waapi-skill.expansion-notice-adjudication/v2`. After the unchanged
complete operation/role attestation, a deterministic per-case
`notice_obligations` projection defines required business meaning. Complete
`attested_roles` remains available to check all affirmative claims. V1 retains
its exact input shape, rubric hash and archive replay; original C09/v1 and
plans without adjudication keep their historical semantics. No historical
judgment is upgraded or rewritten.

C01 retains selected Japanese/Voice and English(US) preservation. C03 requires
both exact existing-target media mappings and identity/Originals preservation;
unchanged SFX and Sound SFX defaults need not be repeated. C06/C08 retain
ownership, new points and shape. Axis labels may resolve through unambiguous
visible prompt/context; old points, delta arithmetic and unchanged domain are
contextual facts. M01 requires one new Segment, two media-bearing Tracks,
exact file associations, Quiet Track Volume -6 dB, Full default Volume and
preserved clip/source gain and music scope. Native AudioFileSource/sequence/
clip enumeration is optional. C08 keeps the weaker Gateway result-schema
boundary, including any required disclosure; it cannot claim Gateway persisted
curve readback or listening proof.

The post-Preview notice must visibly communicate or adopt the specific plan.
Sealed operations cannot supply absent intent. Preservation shorthand is
sufficient only when it unambiguously adopts the full explicit scope. Wrong
mappings, languages, fields, values, quantities, protected edits, false optional
claims and weaker-verifier overclaims remain non-PASS. No parser, business
prompt, oracle, authorization or product runtime change accompanies this repair.

The [source-only audit](../../docs/research/integration-expansion-notice-obligation-audit-8550bdd.md)
grounds prospective contrasts. Three copied C03/C06/M01 pre-execution-only
inputs preserve exact source hashes, complete attested facts and visible text;
their tests regenerate roles/projection without historical regrading. Fake
reviewer contrast tests prove producer-to-input transport, receipt binding and
read-only full-archive replay, including original v1 and new v2 contracts,
non-PASS receipts and obligation/contract substitution rejection. They do not
establish language accuracy or grant semantic PASS credit. Held-out independent
review, promotion gates and new frozen Fresh acceptance remain separate work.

## Intent and verification attribution checkpoint — consolidated #147

New plans use `waapi-skill.expansion-notice-adjudication/v3`. The
[source-only rationale](../../docs/research/integration-expansion-notice-intent-audit-71f1a09.md)
and two exact C06/C08 pre-execution inputs establish the prospective repair
scope; they provide no historical regrade or formal outcome. V1 and v2 retain
their exact input shape, rubric hashes and sealed archive replay.

V3 separates required visible preservation intent from protected background
invariants. An unambiguous exclusive requested-edit plan adopts the user's full
preservation scope without enumerating every oracle guard. Future verification
uncertainty does not revoke that intent; explicit protected edits and uncertain
edit scope remain non-PASS. Complete attested facts remain available for false
claim checks. Every target, action, mapping, field, value, count and curve
requirement, and every authorization/execution/oracle/provenance gate, remains.

V3 also separates transaction strength from a planned requested public read.
The operation-bound verification context records packaged reader support and
source-controlled disclosure timing, without claiming live availability,
discovery or a completed read. Operation, Skill and explicit user requirements
control warning timing; there is no unconditional pre-Execute schema-only
phrase requirement. Terminal strength/boundary reporting, false persisted or
stronger-verifier attribution, listening claims, unsupported proof, raw/code
bypasses and retries retain their limits. The transaction stays closed.

The existing isolated reviewer, schema, bounds and formal Fresh harness are
reused, including the 2048-byte effective instruction ceiling. Copied-witness
projection and real producer-to-archive tests preserve complete source facts;
independent positive/negative contrasts prove fake-judgment transport and
non-PASS propagation only. They grant no language accuracy or semantic PASS
credit. Product Skill, business prompts and oracles are unchanged. Full Non-live
and new frozen Fresh acceptance remain promotion work.

This isolated macOS developer checkpoint passed the four focused reviewer/
producer/archive/CLI files: 429 passed, 1 native-Windows UNC case skipped.
The fixed `notice-fast` gate then passed 3678, with that same single skip;
both commands exited 0 through `ci/test.sh` with the pinned developer Python.
These counts are developer evidence only. No full Non-live, Wwise, Codex turn,
formal semantic acceptance or native-Windows execution occurred in this repair.

## Pre-execution read evidence checkpoint — consolidated #147

New expansion plans use `waapi-skill.expansion-notice-adjudication/v4`.
The outcome-blind e1f3e9b audit identified one confirmed producer omission:
C01's Agent had already read Backup's children through the authenticated
public query and received count 0 / objects [], while the reviewer saw only
Agent text and selected oracle facts. The copied pre-execution witness retains
that read at event 29 / Broker sequence 11 and its preceding scalar read at
event 26 / sequence 10. Source file hashes and original positions are recorded;
the test's placeholder timeline is explicitly a reconstruction with its own
hash, never the source timeline. No judgment or after-state was copied.

V4 projects existing admitted successful public query rows and metadata
results, plus small schema/status identifiers, through the existing Broker
and input-builder seam. Exact request scope, returned field absence/null/empty
values, completeness markers, event position, Broker sequence, payload and
record digests remain bound to the pre-Execute timeline. Replaying the existing
read admission checks adds no Wwise call. Validated ceiling-limited rows remain visible with `scope_complete=false`;
partial results cannot establish complete absence, and failed reads grant no
factual proof. The existing business-proof read policy is unchanged. Endpoint/session,
continuation authority and raw transcript envelopes do not cross into review.
The complete input retains its 128 KiB ceiling and fails closed rather than
silently dropping acquired facts.

Packaged ordinary object-query support is disclosed separately from actual
acquisition and live availability. V3 already distinguishes natural future
verification plans from acquired or guaranteed proof; v4 adds evidence rather
than phrase exceptions. Exact contiguous quote/event grounding, authorization,
immutable Preview, business oracle and archive gates remain unchanged.
V1/v2/v3 keep their exact input shape, rubric hashes and replay; old FAIL roots
remain frozen. Product Skill, prompts, oracles and reviewer settings are unchanged.

The lightweight retrospective measured about 69.59 minutes across one Non-live
and three Fresh matrices, excluding unmeasured coordination/development. Its
repair package is limited to evidence completeness and exact failed-read
receipt admission. Focused tests and `notice-fast` precede one combined parent
Non-live promotion gate; no new model/Wwise execution or historical regrade
is implied by this checkpoint.

The merged a0d0414 developer base plus this v4 repair passed the four focused
reviewer/producer/archive/Broker files: 391 passed, one native-Windows UNC case
skipped. The fixed `notice-fast` gate passed 3715 with that same skip; both
exited 0 through `ci/test.sh` and the pinned developer Python. These are fake
developer proofs only; the combined Non-live and real/Fresh gates remain separate.

The incremental review correction retains owned-project ceiling rows after
checking their identities; malformed rows and unknown false-observation causes
still fail closed. The exact public query timeout helper also drives archive
terminal enforcement: later dispatch and fabricated PASS are rejected while
an already verified transaction keeps its state. Owned-ceiling producer/archive
contrasts and full fake timeout archives reproduce these two gaps without
model execution, source-oracle changes or historical replay.

After these review corrections, the same focused selection passed 398 with
one native-Windows UNC skip; fixed `notice-fast` passed 3722 with the same skip.
Both exited 0 using the pinned developer interpreter. No Non-live, Wwise or
model execution/replay was run in this correction.

## Reviewer effort checkpoint — prospective v5

New expansion plans use `waapi-skill.expansion-notice-adjudication/v5` and pin
only the independent reviewer to `gpt-6.1-sol`, high reasoning and default
service tier. V5 aliases v4 input/evidence and judgment semantics; the v4 rubric
bytes and schema remain identical. The executor settings, 120-second reviewer
deadline, isolation, hard gates and non-PASS handling retain their existing
contracts. V1–v4 keep medium/default configuration, original rubric/configuration
hashes and sealed replay. This is a bounded judgment-reliability experiment,
not evidence that higher effort fixes any notice or a model ranking.

Both actual Codex commands derive their effort from the source-owned versioned
configuration. The independent invocation binding and receipt seal that setting;
archive replay validates exact argv and rejects contract/effort substitution
without model calls or grade writes. Configuration hashes, v4/v5 input parity,
actual fake subprocess argv, read-evidence replay and resealed tampering have
focused developer coverage. Those fake judgments establish transport and binding,
not language accuracy or semantic acceptance. No old notices are rejudged or
historical FAILs upgraded; new Fresh workflows and final full acceptance remain
separate promotion gates.

This macOS developer patch passed the four affected reviewer/producer/archive
files: 2401 passed and one native-Windows UNC case skipped. The fixed
`notice-fast` gate passed 3731 with the same skip; both exited 0 through
`ci/test.sh` with the pinned developer Python. No full Non-live, native-Windows,
Wwise or Fresh model acceptance was run for this checkpoint.
