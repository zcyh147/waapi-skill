# Five-version executable WAAPI coverage

This file describes the packaged interface contract. It is not a claim that
every endpoint has been exercised against a live Wwise installation.

## Coverage snapshot

The default `wwise-console` profile retains the canonical WwiseConsole
reflection and route contract:

| Wwise | Reflected | Direct packaged route | Confirmed transaction route | Excluded | Packaged route rows |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021.1 | 126 | 45 | 79 | 2 | 124 (97 functions + 27 topics) |
| 2022.1 | 144 | 55 | 87 | 2 | 142 (110 functions + 32 topics) |
| 2023.1 | 181 | 57 | 122 | 2 | 179 (147 functions + 32 topics) |
| 2024.1 | 178 | 54 | 124 | 0 | 178 (148 functions + 30 topics) |
| 2025.1 | 185 | 57 | 128 | 0 | 185 (154 functions + 31 topics) |
| Total version/API rows | 814 | 268 | 540 | 6 | 808 |

The 808 packaged route rows represent 198 unique public WAAPI route contracts
across the five versions. A hard boundary is never counted as routed coverage.
This is not the number dispatchable on WwiseConsole: the three UI-command
routes retained in each 2021.1–2023.1 Console-reflected manifest still require
a live Authoring host and return `AUTHORING_HOST_REQUIRED` before business
dispatch on WwiseConsole.

The separate `wwise-authoring-ui` profile is the Console manifest plus reviewed
Authoring UI-command, UI-topic, and core/UI supplements:

| Wwise | Packaged overlay rows | Packaged route rows | Functions | Topics | Registry exclusions |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021.1 | 126 | 126 | 99 | 27 | 0 |
| 2022.1 | 144 | 144 | 112 | 32 | 0 |
| 2023.1 | 181 | 181 | 149 | 32 | 0 |
| 2024.1 | 195 | 195 | 161 | 34 | 0 |
| 2025.1 | 203 | 203 | 168 | 35 | 0 |
| Total version/API rows | 849 | 849 | 689 | 160 | 0 |

Those rows represent 203 unique packaged URI contracts, not 849 calls proven
executable on Authoring. This union retains Console-only rows; 16 inherited
functions were absent from each 2024/2025 live Authoring inventory in the
2026-09-13 audit. This is not a complete Authoring manifest
reflection: runtime metadata deliberately reports
`full_authoring_inventory_reflected: false`. The live gateway selects this
profile only when `ak.wwise.core.getInfo` reports
`isCommandLine: false`; UI-command requests sent to WwiseConsole fail with an
Authoring-host boundary before the target API is dispatched.
The supplements include the five UI-command schemas, reviewed UI topics,
nine remote/selection/foreground/project functions in 2024.1 and 2025.1,
and `ui.getSelectedFiles` in 2025.1 only. Other rows come from Console.
The user-approved product exclusions remain outside the packaged union:
the observed `ui.layout.*`, `ui.model.*`, `ui.window.*`, `ui.signal.emit`,
`ui.cli.executeLuaScript`, and `ui.cli.launch` delta (27 unique functions,
52 version rows). They remain part of any full live Authoring denominator;
they are not evidence of missing Wwise functionality.

## Route meanings

- `fixed_command`: a dedicated packaged gateway command.
- `bounded_call`: a reviewed read-only route selected by `request-schema`; its
  typed continuation has recursive reflected request/result validation, a
  timeout, and a result-size ceiling.
- `bounded_topic_wait`: a configurable finite or explicitly no-timeout wait
  that remains event-count/result bounded and always unsubscribes. Explicit
  continuous requests use `stream-topic`, whose persistent subscription has an
  explicit event-count and cumulative-output bound, emits bounded records, and
  also unsubscribes on termination.
- `transaction`, `managed_transaction`, or `isolated_transaction`: a named
  `operation-schema` or exact-URI `request-schema` typed route through immutable
  Preview -> accepted authorization -> execute once -> result verification.
  The materialized canonical request may use `waapi.call` internally, but that
  representation is never a caller or model input.
  For project changes, `ask_before_changes` presents the expected result and
  waits for a later explicit confirmation, while `allow_changes` gives notice
  and may continue from durable policy authorization in the same user turn;
  `read_only` blocks the change.
- `compound_transaction_member`: one Undo member row that remains executable
  only inside the closed `waapi.undoGroup` same-connection composite; it is
  not independently executable and is constructed only through the Undo
  child typed contract.
- `excluded`: no public execution route and no connection attempt.

Every route is implemented in the Skill runtime. An agent must not replace a
route with inline Python, a temporary helper, direct `WaapiClient` code,
model-authored/hidden Lua, or a raw MCP call.

Isolated routes recursively audit filesystem-looking fields. Read inputs must
be absolute; explicit writes must resolve under a non-root `io_root`, including
through existing symlinks. Wwise-managed implicit outputs are reported as
unproven rather than falsely described as confined. Model-supplied CLI custom
command hooks are rejected. Managed session openers publish a digest-bound
cleanup spec, exact companion request, and phase status instead of hiding a
lifecycle obligation. Transport destroy is bound from the validated create
result; Work Unit load/unload is an available reversal, not required cleanup.

## Exact registry exclusions and host prerequisites

### Default `wwise-console` profile, Wwise 2021.1–2023.1

- `ak.wwise.ui.commands.register`
- `ak.wwise.ui.commands.execute`

### Default `wwise-console` profile, Wwise 2024.1–2025.1

No reflected Console-manifest row is a registry exclusion; the five UI-command
rows are absent from these two Console manifests and appear only in the
Authoring overlay.

### `wwise-authoring-ui` profile

No reflected row is excluded. The three modifying UI-command functions are
available only through closed named transactions:

- `ui.commands.execute` accepts bounded fields, verifies the command ID against
  the current live inventory immediately before its one non-retried dispatch,
  and reports result-schema-only verification because an arbitrary GUI/project
  effect has no general readback.
- `ui.commands.register` accepts closed notification/program/Lua descriptors,
  binds local paths and content, and verifies the registered IDs through a
  fresh live inventory. Program or Lua handlers require the exact
  `user_supplied_verbatim` caller assertion; it is not runtime proof of
  conversational provenance. Register and descriptor-backed unregister derive
  the platform only from live `getInfo.platform`: `x64`/`win32` map to
  `windows`, `macosx` maps to `macos`, and every other or missing value fails
  closed.
- `ui.commands.unregister` requires exactly one request form: closed
  `commands` descriptors (plus `source_authority` when required), or
  `command_ids` with the explicit
  `unregister_existing_commands_without_definition` acknowledgement. Mixing
  forms is rejected. Both standalone modes have unknown ownership and no
  inverse. Descriptor-backed mode seals the requested deletion definition and
  applicable local path evidence, but live inventory proves only ID membership,
  not a matching live definition. A reversible unregister exists only as the
  journal-bound cleanup companion of a successfully executed and verified
  earlier register transaction; a register preview alone is insufficient.

All five `ak.wwise.ui.commands.*` routes require a live Authoring host,
including UI rows already present in the 2021.1–2023.1 Console-reflected
manifests. WwiseConsole returns `AUTHORING_HOST_REQUIRED` before dispatch.

The five reflected `getCommands` inventory sizes were 317, 451, 475, 594, and
623 for Wwise 2021.1 through 2025.1. These files record the current project,
plug-ins, add-ons, and build at collection time. They are evidence snapshots,
never cross-machine allowlists or substitutes for the pre-dispatch live read.

Lua file operations are executable only from an existing `.lua` file whose
path, size, and content hash are rebound, while Wwise 2025.1 also has an exact
inline-source operation. The required source-authority value is a caller
assertion, not runtime provenance proof. Hidden/model-authored source and
unrestricted loader fields remain closed. Private debug reads have fixed
bounded routes, process mode changes have confirmed non-retry transactions,
`assertFailed` has a bounded topic wait, and restart/assert/crash use dangerous
once-only terminal transactions with explicit indeterminate lifecycle
evidence.

## Inspect aggregate counts and exact packaged route lists

For aggregate counts across all five supported versions, choose the requested
scope. These are unfiltered offline summaries, not live reflection:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py capabilities --all-versions --summary-only
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py capabilities --all-versions --summary-only --profile wwise-authoring-ui
```

The first is the Console baseline; the second is the packaged union with the
reviewed Authoring supplements. Each summary contains each version's `total` and every
`preferred_routes` count, including `transaction_operation` and
`unsupported_boundary`; zero-valued route counts remain explicit. Do not combine `--summary-only` with row filters.

For row-level inventories, omit `--summary-only` and use the offline catalog
filters instead of copying a static API list into a prompt:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 capabilities --limit 0
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 capabilities --route transaction_operation --limit 0
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 capabilities --route unsupported_boundary --limit 0
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2025.1 capabilities --profile wwise-authoring-ui --query ak.wwise.ui.commands --limit 0
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py describe ak.soundengine.getState --all-versions
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2025.1 describe ak.wwise.ui.commands.execute --profile wwise-authoring-ui
```

The offline `--profile` switch only inspects packaged catalog data. It cannot
force a live Console connection into the Authoring profile; live host selection
remains gateway-owned.

The catalog and execution registry are tied to an immutable per-version
inventory digest. A URI addition, removal, or same-count substitution fails
closed until the packaged contract is reviewed and updated.

The deterministic [full-surface release report](../../../docs/full-surface-release-report.json)
binds the exact 849-lane inventory digest to its zero/inline/draft/Topic
construction totals, host overlays, execution routes, public continuations,
blocked fields, duplicate-lane audit, schema keywords, and references. It is a
code-only construction report, not real-host or Fresh Agent evidence.

## Verification scope

The Program gate exercises
all 808 packaged route-contract version/API rows with
in-process fake clients. It validates exact URI dispatch, reflected request and
result/event schemas, timeout/result ceilings, all three modification-policy
branches, transaction preparation and verification, same-connection Undo execution, lifecycle cleanup binding,
isolated path confinement, and topic subscribe/event/unsubscribe behavior for
configurable finite or explicitly no-timeout event-count-bounded waits plus
continuous `stream-topic`. Separate negative tests cover exclusions,
route bypass attempts, model-authored external command hooks, malformed nested
payloads, and manifest drift. Reflected and isolated typed transactions also run
through complete preview/confirm/execute/verify program chains. Dedicated tests
separately validate the 849-row packaged union, its supplements, and scoped
Authoring transaction chains; this is not a second 849-row per-API fake-dispatch
matrix. Exact completed run counts and candidate commits are recorded in the
repository's `tests/TEST_INVENTORY.md`, not inferred from this coverage table.
The query tests cover
all five versions of the closed business compiler plus the advanced WAQL route's fixed
read-only URI, UTF-8 byte limits, trimmed single-line framing (no comments,
semicolons, or unclosed string/regex literals), Gateway-appended final `take`,
response cap, and explicit lack of a mutation-identity bridge. Dedicated
program tests also cover five context/read optimizations: compact default query
replies, opt-in `--detail` diagnostics, direct canonical relationship-GUID
hops, request/preview-local identity/property-metadata cache reuse, and
deduplicated bounded multi-ID prepared-role revalidation. They do not prove
native syntax acceptance by a real Wwise process.

The completed, memory-off `h80-release-c38` Codex Terra campaign ran 80
real-Wwise business scenarios for the 16 approved heavy APIs: 70 on 2022.1,
five on 2024.1, and five on 2025.1. All 80 passed with sandbox cleanup and
sealed evidence. That result applies only to the exact heavy-suite candidate;
the later reflected-identical 2025.1 `audio.convert` mapping and the wider 808
row interface remain “program-tested packaged coverage,” not individually
live-semantic-verified.

For the historical modification-policy candidate, the sealed, memory-off
`campaign-modification-policy-9-c7` Codex Terra campaign passed all nine
Wwise 2022.1 tasks and all 15 user turns. It ran three isolated repetitions
each of `read_only`, question-style `ask_before_changes`, and same-turn
`allow_changes`. The three read-only cases performed no primary mutation
dispatch. Each of the six authorized write cases performed exactly one primary
dispatch and verified seven created objects with 46 passing business
assertions. All source-project hashes remained unchanged and all nine
sandboxes were cleaned. This is focused policy behavior evidence, not
per-API or cross-version semantic coverage.

The original five Authoring UI-command resources were collected from matching installed
builds with exactly 35 read-only calls in total: per version, one `getInfo`,
five fixed-URI `getSchema` calls, and one `getCommands`. No live
`execute`, `register`, or `unregister` call was made. Later reviewed Topic/core
supplements have separate reflection evidence. The 2026-09-13 core addition
collected 19 schemas and tested selected-object reads on 2024/2025 and an empty
selected-file read on 2025. It did not execute remote/project/UI mutations.
Schema collection, program tests, real read-only checks, and historical Fresh
Agent scenarios are separate evidence; never combine them into a current
all-API live pass.
