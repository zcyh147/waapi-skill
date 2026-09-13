# Authoring Topic discovery and monitoring repair — 2026-09-13

Base: `cf71264`; working branch: `codex/fix-authoring-topic-monitoring`.
This is a post-release, scoped repair. No project reset, import replay, menu
execution, Windows campaign, or Fresh Agent run was performed.

## Diagnosis and live reflection

The documentation demo failed before subscribing because the packaged Console
inventory omitted Authoring-only Topics from 2024 onward. Missing packaged
reflection was incorrectly presented as a Wwise version limitation.

The user opened each matching Authoring version on macOS. Collection used the
public Gateway's `status`, the sole typed `getFunctions`/`getTopics`
continuations, and `waapi-schema`. Calls were read-only against the already-open
projects. No project cleanliness or source-hash claim is inferred from that.

| Authoring build | Functions | Topics | Compared with canonical Console inventory |
| --- | ---: | ---: | --- |
| 2021.1.14.8108 | 99 | 27 | URI lists identical |
| 2022.1.19.8584 | 112 | 32 | URI lists identical |
| 2023.1.19.8928 | 149 | 32 | URI lists identical |
| 2024.1.13.9056 | 170 | 34 | 38 extra / 16 absent functions; 4 extra Topics |
| 2025.1.7.9143 | 179 | 35 | 41 extra / 16 absent functions; 4 extra Topics |

For 2024/2025, `ak.wwise.ui.commands.executed` was already included in the
separate five-URI commands supplement. The three additional Topics are
`ak.wwise.ui.selectionChanged`, `ak.wwise.ui.signal.click`, and
`ak.wwise.ui.signal.toggle`. Their schemas were independently collected from
each matching version, not copied from 2022.

All five installed SDK CHM files contain `ak_wwise_ui_selectionchanged.html`.
Documentation corroborates the selection event, but did not substitute for
runtime inventory discovery. In particular, the two signal Topics were present
in the 2024/2025 runtime inventories without matching pages found in this search.

Raw evidence (ignored local state, retained):
`.waapi-skill-state/evidence/authoring-topics-20260913/`.
The committed `authoring-ui-topics-supplement.json` files preserve the three
version-matched schemas and build provenance. Canonical JSON digest checks
reject content changes while accepting Windows CRLF checkout differences.

## Scope and behavior

- Console resource inventories remain unchanged. The Authoring profile gains
  six version/Topic rows, for 830 packaged rows and 202 unique URIs. This remains
  Console plus reviewed supplements, not a complete Authoring inventory or a
  claim of 830 real executions. Other newly observed Authoring functions were
  recorded, not automatically exposed.
- The four `ui.commands` functions plus `commands.executed` remain available
  in every supported Authoring version. Command-ID inventories are environment
  snapshots; actual command availability still requires live `getCommands`.
- Count-based or per-event intent selects `stream-topic`, without adding the
  vague observation's 10-second total deadline. One subscription stops at its
  requested count or a declared termination condition.
- Without an explicit total duration, a stream defaults to 300 idle seconds.
  Matching events reset that clock. `--idle-timeout 1800` selects 30 idle minutes;
  `--no-idle-timeout` disables it. Explicit total duration disables only the
  implicit idle cutoff and may coexist with an explicit idle duration.
- Idle termination reports `status=stopped`, `completion_reason=idle_timeout`,
  observed/target counts, and cleanup. It never claims the target count completed
  and does not automatically resubscribe. These options apply at startup; there
  is no hot-reconfiguration command for an existing subscription.
- The 64-event ceiling is a Skill resource policy, not a limit passed to WAAPI.
  Count, buffer, output-byte, host-health and cleanup safeguards remain.

## Validation evidence

- Deterministic reproduction: the new 2024/2025 offline `topic-schema` regressions
  failed with `TypedTopicError` before repair, then passed. All six added
  version/Topic input contracts compile; the generated definition audit has no
  unresolved references or unknown schema keywords.
- Five-version fake-client selection monitoring: 10 parameterizations passed,
  including Authoring event delivery/count completion/unsubscribe and Console
  refusal before subscription.
- Program: **4960 passed, 2 skipped**, exit 0, 201.93 seconds. Skips are native
  Windows-only proof. This is macOS program evidence, not native Windows testing.
- Full Non-live: **10555 passed, 2 failed, 113 skipped, 27 deselected**, 684.51
  seconds. The failures were old document-wording assertions and the fixed
  Program manifest count (182 versus 187). Only those tests were corrected;
  their targeted rerun passed **2/2** in 0.27 seconds, with no runtime changes.
  This is full-run plus scoped correction evidence, not a single all-green root.
- Real 2024 Authoring: an eight-second Gateway stream received one selection
  event (`Car Engine`) and exited with `cleanup=unsubscribed`, exit 0. Its goal
  was two events; the terminal truth is **1/2**, `duration_elapsed`, not count
  completion. The user supplied the UI interaction. This proves real subscription
  and event delivery, not a Fresh Agent natural-language routing PASS.
- Event readback retains the pre-existing partial validation boundary: the
  general semantic validator reports the nested `objectReturn` `$ref` as
  unresolved while checking outer structure. This was not reclassified as full
  nested-field validation or expanded into a validator rewrite.
- The repository's Skill protocol/size checks passed. The optional system
  `skill-creator` validator could not run because PyYAML is absent from the
  existing Poetry and bundled interpreters; no dependency was installed or
  added to the packaged Skill to satisfy that unrelated tool.

## Handoff

The changed packaged files were synchronized to
`/Users/xiye/Documents/Git/waapi_skill_test/.agents/skills/waapi-skill` after
checking the old files against the base revision, then compared byte-for-byte.
Its `.venv`, configuration and projects were preserved. Use a fresh task for the
next demonstration; a task that already read the old Skill retains old routing
instructions. Fresh Agent routing acceptance and signal-widget event effects
are not claimed by this repair's evidence.

An incidental maintenance-interface issue was observed but not changed here:
`request-schema ak.wwise.waapi.getSchema` advertises generic `--value` input forms,
whereas the public `waapi-schema --help` uses a positional URI. Reflection used
that existing public positional form; no direct client bypass was used.
