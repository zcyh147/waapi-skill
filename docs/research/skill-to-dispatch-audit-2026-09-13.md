# Skill-to-dispatch audit — 2026-09-13

Candidate: `94dbd8091ff418de9c5fa5f09db96b8cb3debd82`.
This is an audit, not a repair or merge. Runtime, Skill instructions, tests,
configuration, installed demonstration copy and Wwise projects were not changed.
Only this report was added. No Fresh Agent or real WAAPI mutation was run.

## Scope and method

Read SKILL.md and all four active lane references, ADRs 0001–0003, the launcher,
compact/detailed operation discovery, Console/Authoring capability selection,
the nineteen new version/function schema continuations, host-plan compilation,
Draft check, Preview, authorization, execution lease, dispatch and verification.
Follow the new Authoring routes and the shared discovery/documentation paths;
this is not an exhaustive semantic proof of every WAAPI property or API.

Evidence is from public offline Gateway commands, code inspection, deterministic
in-memory compiler probes, and six fake-client transaction chains using the
repository's existing test helpers. No new agent-semantic harness was created.

## Findings

### F1 — High priority: omitted discard intent does not protect unsaved work

`wwise_waapi/host_ui_debug_business.py:275–299` omits `bypassSave` when the user
does not supply the corresponding optional discard field. The separately
collected 2024/2025 Authoring schemas describe native `bypassSave` as defaulting
to true: the user is not prompted to save the current project.

The ordinary instruction to omit unrequested optional fields therefore leaves
the save-prompt behavior to that native default. Project transition guards
check endpoint/version/runtime and project identity/path/state; the transition
projection in `gateway.py:28821` does not include dirty/unsaved state.
Normal Preview authorization is not an explicit instruction to discard work.

An offline compiler probe of open/close on both versions produced only
`{"path": "/tmp/waapi-audit-target/Target.wproj"}` / `{}`. A check requiring
`bypassSave=false` for omitted discard intent failed in all four cases.
This confirms a missing protection/default, not observed data loss. The audit
did not test native behavior against a dirty user project.

Repair: make the non-discard intent explicit inside the Gateway; handle dirty
state, native save prompts and timeout/cancellation without retrying an
uncertain transition. Only explicit discard intent may take the discard path.
Review both old and newly added versions because the compiler is shared.
Do not solve this by asking the model to remember an extra flag.

### F2 — High priority: ordinary discovery hides the needed business routes

SKILL.md:106 and waapi-operate.md:33 require natural-language changes to select
the first contract from the compact `operations` result, and prohibit URI
invention. They reserve `operations --detail` for explicit complete audits.

The compact result exposes 33 named operations and merely reports a count of
105 reflected-URI business routes. `gateway.py:9740` includes the latter list
only under `--detail`. It contains project open/close/create and remote.connect,
but ordinary Agent use is instructed not to request it.

Furthermore, even the detailed business-route list does not include remote
disconnect/status/available-consoles, bringToForeground, or getSelectedFiles.
They have exact-URI schema contracts, but no business catalog entry. Adding
only a getSelectedFiles sentence does not repair this shared discovery gap.
The direct `selected` route is already described and remains discoverable.

Repair: one compact, version-aware business catalog covering permitted named,
reflected and zero-input/fixed routes, with intent, host requirement and exact
next command. Keep detailed argument schemas behind their existing schema
commands. Audit the other hidden business families, not only the latest ten
URIs. This need not introduce another intent LLM or raw native-input fallback.

### F3 — Medium priority: offline host defaults contradict the normal read path

The default capability/describe profile remains Console. On 2025.1,
`capabilities --query remote --limit 0` returns zero matching rows; the identical
command with `--profile wwise-authoring-ui` returns all four remote rows.
Default `describe ak.wwise.ui.getSelectedFiles` reports CapabilityNotFoundError,
while exact `request-schema` succeeds.

waapi-query.md:10 sends known URIs to `describe`; waapi-setup.md:80 says only the
five UI-command APIs depend on the Authoring profile. Both are inconsistent
with the current topic/core supplements. Live auto-detection is working; this
is an offline discovery/instruction mismatch, not permission to add a live
caller-controlled host override.

Repair: disclose the appropriate offline host scope without implying live
support from an offline list; align known-URI and ordinary business lookup
rules with the existing actual-host dispatch gate.

### F4 — Medium priority: active instructions retain retired input mechanics

SKILL.md:153 still says `Import alone uses token custom-field binding`, despite
the public token binder having been removed. The same paragraph directs
object.create through pre-Draft metadata discovery, while the current
waapi-operate.md:98 and business contracts require Draft-owned discovery.

waapi-query.md:18–22 describes native Media Pool databases/filters/maxResults,
native field names, native operator objects and an Agent-owned return list.
The current `request-schema ak.wwise.core.mediaPool.get` instead exposes
closed business flags such as --text-filter, --number-filter, --include-field,
--max-results and their scoped meanings. Keeping both instructions invites
model-authored native details even though the runtime rejects that ingress.

Repair: remove retired descriptions and make the returned business contract the
single authority. Scan all four current references for old input/order claims;
do not add a growing table of native payload recipes to SKILL.md.

### F5 — Medium priority: packaged coverage guidance is stale/mis-scoped

waapi-coverage.md still records the 824-row/200-URI Authoring snapshot and
states that all 824 rows route on a matching Authoring host. Current candidate
resources represent 849 rows/203 unique URIs in the Console-plus-reviewed-
Authoring union, not a pure Authoring host execution set. The historical live
report already proves 16 Console-only functions absent from each later
Authoring host. Its old Program counts are also not current-candidate results.

The active Skill instructs coverage requests to use the Console-default summary
as though it includes every route. The newer research report does not replace
this active packaged reference for normal Agent use.

Repair: distinguish host-specific reflected availability, packaged routing,
explicit prohibited boundaries and actual tests; label historical evidence by
candidate. Preserve the user's 27-URI product exclusions rather than removing
them from the observed Authoring denominator.

### F6 — Medium priority: full-chain sampling omits the new Authoring rows

`tests/unit/test_transaction_gateway.py:221` builds PROJECT_TRANSITION_ROWS from
ExecutionContractRegistry.entries(version), the Console-only profile. An
explicit check for the six 2024/2025 ui.project rows returned [] and failed.
Thus the test named every_project_transition_row does not cover them.

For this audit only, the existing test function was exercised in memory with
two fixture adaptations: retrieve the approved Authoring contract and use the
new reflected empty close result. Production code was unchanged. After resolving
the temporary root's macOS /var symlink (the first fixture attempt correctly
failed storage safety checks), all six open/close/create fake chains passed:
Preview -> confirm -> execute once -> verify matching project postcondition.
This proves those code paths are connected; it does not prove dirty-work
preservation, native GUI behavior, or natural-language route discovery.

Repair: permanently select the proper host profiles in the test matrix; add
entry-to-contract reachability and omitted/explicit-discard cases. Keep tests
at public boundaries and avoid exact user-facing sentence matching.

## Positive findings and limits

- All 19 exact-URI `request-schema` calls succeeded and returned the expected
  business Draft, zero-input continuation, or fixed selected route.
- The six project transaction mock chains passed as described above.
- Read-only/mutation classification, version/resource pins, immutable Preview,
  authorization checks, execution lease, execute-once and postcondition guards
  remain in the reviewed call path. No new raw-input or direct-client bypass
  was confirmed by this audit. This is not a proof that all possible bypasses
  or all unrelated APIs are defect-free.
- The missing core JSON entry in the runtime fingerprint list was inspected:
  the new loader independently pins its canonical digest in fingerprinted Python
  and checks it when resolving these routes. It is not reported here as a
  confirmed unguarded-resource vulnerability.
- Historical Program 5061/2 is unchanged prior-run evidence. This audit did not
  rerun the entire gate, launch a Fresh Agent or mutate any live Wwise process.

## Revised implementation scope

The earlier phrase “one small step” was too narrow. Before merging:

1. Fix safe project-transition defaults and add non-discard regressions.
2. Complete compact business discovery, including zero-input reads/mutations,
   while retaining exact version and host boundaries.
3. Align Skill/setup/query/operate/coverage guidance with current contracts.
4. Expand the existing public-boundary tests to cover route discovery and new
   Authoring transaction chains, then run proportional Program/non-live gates.

These are localized safety, discovery, guidance and test-sampling corrections,
not grounds to replace the Gateway architecture or rerun the complete expensive
Fresh Agent matrix. Tiny targeted offline Fresh probes can be evaluated after
deterministic discovery checks pass, but are not part of this audit.

## Authorized repair — code candidate `249fc75`

The user approved repair after the audit. The findings above remain the
pre-repair record at `94dbd80`; the following work closes F1–F6 in the scoped
program/interface sense, not as new real-Authoring or Agent evidence.

- F1: the shared project open/close business compiler now always supplies
  `bypassSave=false` when discard is omitted. Explicit false/true is preserved.
  The business contract discloses the safe default, explicit discard intent,
  human-owned save prompts and the no-replay boundary. All five versions cover
  omitted/false/true choices. Public Draft-to-Preview checks prove the default
  reaches the immutable artifact. Existing execution/verification logic was
  retained; new fake-client cases prove a timeout stays INDETERMINATE and never
  redispatches, and an unchanged post-state is not reported as successful.
- F2/F3: compact `operations` exposes version-filtered business adapters and
  reviewed fixed/zero-input routes, with copy-ready next commands and host
  scope. Detailed mode retains all-version inspection and reports differing
  host surfaces by version. The directory derives from existing registries,
  not a second raw-input route. Every emitted schema link is checked offline
  across five versions; all 19 approved additions are reachable. Live host
  detection is unchanged. Offline Console defaults are now explicit in the
  Skill's inspection guidance.
- F4: Skill/query/operate guidance follows business declarations and Draft-owned
  field discovery. Retired import-token binding, caller-built import paths and
  native Media Pool payload recipes are removed. Operation-specific native
  details stay behind the returned schema. The original 20,000-byte CRLF lane
  document bounds are preserved, not increased to accommodate new text.
- F5: coverage guidance records the generated 849-row/203-URI packaged union,
  separates host availability from packaging, retains the 27 excluded URIs in
  live-inventory denominators, and stops presenting old test counts as current.
- F6: the complete project-transition matrix includes the six new 2024/2025
  rows and uses their actual reflected result shapes. The host/project Adapter
  test file is now part of the fixed Program gate, including safe-default cases.

### Completed validation and preserved failures

All runs below used macOS and fake clients/offline commands. No real Wwise,
Fresh Agent, native-Windows Python gate, project reset, old transaction replay,
or demonstration-Skill synchronization occurred.

1. New safe-default regression before repair: **10 failed / 20 passed**;
   every omitted-discard case exposed the native default leak. After repair,
   the entire Adapter file passed **91 tests**.
2. New compact-directory regression before repair: **2 failed**; after repair
   both passed. Five-version directory-link and public project-open Draft
   checks subsequently passed **10 tests**.
3. Focused Gateway/Authoring/Adapter run: **373 passed**. Supplemental program
   assertions were added afterward and are included in the final Program run.
4. First broad Program: **5058 passed / 10 failed / 2 skipped**, exit 1.
   Failures exposed old hidden-directory/order/wording expectations and the
   document-size limits. Corrected the assertions and shortened documents;
   did not relax the document limits or execution/verification checks.
5. Final fixed Program: **5159 passed / 2 skipped**, exit 0, 257.28 seconds.
   Skips require native Windows shell/NTFS behavior. This covers the final
   runtime and Skill; subsequent edits changed only three tests outside the
   fixed Program selection and evidence documentation.
6. Full Non-live: **10725 passed / 10 failed / 113 skipped / 27 deselected**,
   exit 1, 769.03 seconds. Five failures asserted the retired Media Pool native
   recipe in the query reference; four asserted old documentation/counts; one
   omitted the approved `getSelectedFiles` from the immutable call allowlist
   expectation. They did not reveal a new runtime failure.
7. After test-only corrections, reran all three affected files:
   `test_codex_media_pool_runtime_v3.py`, `test_capability_catalog.py`, and
   `test_skill_gateway_contract.py`: **91 passed**, exit 0, 9.31 seconds.
   Kept native request/result expectations in the Media Pool tests; changed
   only their documentation contract. Call-allowlist checks now separately
   prove the unchanged Console subset and the approved Authoring union.

The full Non-live failure record is not relabelled as a single-root PASS.
Its ten failed tests have passing focused follow-up evidence without any
post-Program runtime or Skill changes. No second full Non-live rerun was made
for these test-only corrections.

The generic skill-creator validator could run in an isolated `uv` environment
but rejects the unchanged Skill description's `<literal-locator>` placeholder
syntax. The Poetry/bundled environments initially lacked its PyYAML dependency.
No project/runtime dependencies or bootstrap description were changed to suit
that ancillary validator. Repository Skill protocol and document-size tests
passed. `git diff --check` passed and no owned pytest/test-driver process
remained after validation.
