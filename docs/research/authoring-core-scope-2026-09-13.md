# Authoring core scope and version repair — 2026-09-13

Base: `918fa505f108d6d1c92364bd7161370349cd8e6a`.
Branch: `codex/authoring-core-2024-2025`.

## User-approved scope

Add nine existing business capabilities to both Wwise 2024.1 and 2025.1:
`core.remote.connect`, `disconnect`, `getAvailableConsoles`,
`getConnectionStatus`; `ui.getSelectedObjects`, `ui.bringToForeground`;
`ui.project.open`, `close`, `create`. All have the `ak.wwise.` prefix.
Add `ak.wwise.ui.getSelectedFiles` to 2025.1 only.
This is ten unique URIs and nineteen version/function rows, not nineteen
new business operations. The nine common URIs already had older-version routes.

The user explicitly excludes the remaining observed Authoring delta from this
release scope: every listed `ui.layout.*` function (including 2025 closeView
and resetLayouts), all five `ui.model.*` functions, all three `ui.window.*`
functions, `ui.signal.emit`, `ui.cli.executeLuaScript`, and `ui.cli.launch`.
These are 27 unique URIs / 52 version rows. Exclusion is a product-scope choice,
not evidence that Wwise lacks them or they are impossible to wrap. Existing
Topic support remains unchanged. Layout APIs include ordinary layout switching,
not only custom layout construction; they are still excluded by user choice.

Keep these rows in the observed Authoring denominator. The preceding article
snapshot remains historical: 2024 had 170/204 present packaged entries, 2025
had 177/214. Construction of the approved additions alone does not convert the
remaining gaps into supported functions or prove actual execution of each row.
Likewise, a catalogued prohibited Debug boundary is not a successfully executed
Debug function.

## Implementation

- Collect exact schemas through the public Gateway, against the user's
  already-running Windows Authoring builds 2024.1.13.9056 and 2025.1.7.9143.
  The gateway and collector run on macOS; this is not a native-Windows Python
  test run. Use only getInfo/status and bounded waapi-schema reads.
- Keep Console reflection untouched. Add a separate nineteen-row Authoring
  supplement with exact version/schema sets, canonical hashes, and build
  provenance; reject missing/changed resources and duplicate substitutions.
- Reuse existing business declarations, immutable Preview, authorization,
  execute-once, project-transition guards, isolated I/O, and verification.
  Explicitly resolve these approved Authoring schemas in construction and
  I/O validation without granting a live host override.
- Select the full reviewed Authoring profile for real Authoring dispatch.
  Preserve historical Console contracts; require Authoring for the new lanes.
  Check the host before Draft validation's read branch, so a switch to Console
  fails with the proper host boundary, not a missing-schema error.
- Reuse the fixed `selected` projection and strict returned object identities.
  `getSelectedFiles` uses the existing schema-disclosed zero-input read with
  bounded result/schema validation. No caller-authored projection or new
  execution framework was added.
- Retain the existing new-version omission of `notification_port`: both new
  remote.connect schemas explicitly describe the native field as `Unused.`.

Raw read-only collection and 2025 probe results are retained under
`.waapi-skill-state/evidence/authoring-core-20260913/`. No original project,
configuration, old Draft, transaction or failed campaign was reset or replayed.

## Validation boundaries

- Initial public `selected` regression: old three versions passed; 2024/2025
  failed because the default manifest blocked selection. After the repair,
  all five parameterizations passed.
- Actual 2024 Authoring `selected` returned `status=ok`, zero selected objects.
- Actual 2025 Authoring `selected` and `getSelectedFiles` returned `status=ok`,
  respectively zero selected objects and an empty files array. These are
  current-state empty-selection proofs, not non-empty selection tests.
- Focused fake-client checks cover exact version routes, tampered/CRLF
  resources, malformed file results, Unicode file paths, remote declaration
  through immutable Preview, and Authoring-to-Console rejection during Draft
  declaration/check. They do not prove native remote connections or project
  transitions on the two new versions.
- The first Program run ended with 5030 passed, 10 failed, 2 skipped. Failures
  exposed stale inventory checks and an overly broad host restriction affecting
  two old-version read-transaction tests. The restriction was narrowed; original
  failed counts are not relabelled as passing evidence.
- No Fresh Agent, full live matrix, real remote connect/disconnect, project
  open/close/create or foreground mutation was performed in this repair.

Final macOS Program gate: **5061 passed, 2 skipped**, exit 0, 222.18 s.
The skips require native Windows shell/NTFS proof and receive no passing credit.
Final focused Non-live selection (CI driver, new Authoring core Gateway tests,
and host/project Adapter tests): **151 passed, 11 skipped**, exit 0, 13.52 s.
Its skips require a Windows cmd.exe executor. The post-Program changes were
limited to those CI-manifest expectation tests and documentation; runtime,
schemas, and the Program manifest stayed unchanged.

The intermediate second Program run remains **5056 passed, 5 failed, 2 skipped**;
all five failures were old count expectations in generated-inventory tests.
Two subsequent focused CI-driver attempts each recorded **150 passed, 1 failed,
11 skipped** before both the node-count and final-node expectations were
updated. They are not relabelled as passes. No full Non-live run was performed
for this change; the passing focused selection is not full-suite evidence.

Commands:

```sh
ci/test.sh --mode program -- -q -ra --tb=short
ci/test.sh --mode nonlive -- tests/unit/test_ci_test_bat.py tests/unit/test_authoring_core_gateway.py tests/unit/test_host_ui_debug_business_adapter.py -q --tb=short
```
