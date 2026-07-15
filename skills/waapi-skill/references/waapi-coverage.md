# Five-version executable WAAPI coverage

This file describes the packaged interface contract. It is not a claim that
every endpoint has been exercised against a live Wwise installation.

## Coverage snapshot

| Wwise | Reflected | Direct packaged route | Confirmed transaction route | Excluded | Executable |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021.1 | 126 | 43 | 76 | 7 | 119 (93 functions + 26 topics) |
| 2022.1 | 144 | 52 | 85 | 7 | 137 (106 functions + 31 topics) |
| 2023.1 | 181 | 53 | 117 | 11 | 170 (139 functions + 31 topics) |
| 2024.1 | 178 | 49 | 119 | 10 | 168 (139 functions + 29 topics) |
| 2025.1 | 185 | 50 | 125 | 10 | 175 (145 functions + 30 topics) |
| Total version/API rows | 814 | 247 | 522 | 45 | 769 |

The 769 executable rows represent 188 unique public WAAPI URIs across the five
versions. A hard boundary is never counted as executable coverage.

## Route meanings

- `fixed_command`: a dedicated packaged gateway command.
- `bounded_call`: a reviewed, read-only `call` route with recursive reflected
  request/result validation, a timeout, and a result-size ceiling.
- `bounded_topic_wait`: one bounded subscription followed by guaranteed
  unsubscribe.
- `transaction`, `managed_transaction`, or `isolated_transaction`: the
  manifest-registered `waapi.call` operation through immutable
  preview -> explicit confirmation -> execute once -> result verification.
- `compound_transaction_member`: one Undo member row that remains executable
  only inside the closed `waapi.undoGroup` same-connection composite; it is
  rejected from independent `waapi.call` execution.
- `excluded`: no public execution route and no connection attempt.

Every route is implemented in the Skill runtime. An agent must not replace a
route with inline Python, a temporary helper, direct `WaapiClient` code, Lua,
or a raw MCP call.

Isolated routes recursively audit filesystem-looking fields. Read inputs must
be absolute; explicit writes must resolve under a non-root `io_root`, including
through existing symlinks. Wwise-managed implicit outputs are reported as
unproven rather than falsely described as confined. Model-supplied CLI custom
command hooks are rejected. Managed session openers publish a digest-bound
cleanup spec, exact companion request, and phase status instead of hiding a
lifecycle obligation. Transport destroy is bound from the validated create
result; Work Unit load/unload is an available reversal, not required cleanup.

## Exact exclusions by version

### Wwise 2021.1 and 2022.1

- `ak.wwise.ui.commands.register`
- `ak.wwise.ui.commands.execute`
- `ak.wwise.debug.enableAsserts`
- `ak.wwise.debug.enableAutomationMode`
- `ak.wwise.debug.testAssert`
- `ak.wwise.debug.testCrash`
- `ak.wwise.debug.assertFailed` (topic)

### Wwise 2023.1

- `ak.wwise.ui.commands.register`
- `ak.wwise.ui.commands.execute`
- `ak.wwise.cli.executeLuaScript`
- `ak.wwise.core.executeLuaScript`
- `ak.wwise.debug.enableAsserts`
- `ak.wwise.debug.enableAutomationMode`
- `ak.wwise.debug.getWalTree`
- `ak.wwise.debug.restartWaapiServers`
- `ak.wwise.debug.testAssert`
- `ak.wwise.debug.testCrash`
- `ak.wwise.debug.assertFailed` (topic)

### Wwise 2024.1 and 2025.1

- `ak.wwise.cli.executeLuaScript`
- `ak.wwise.core.executeLuaScript`
- `ak.wwise.debug.enableAsserts`
- `ak.wwise.debug.enableAutomationMode`
- `ak.wwise.debug.getWalTree`
- `ak.wwise.debug.restartWaapiServers`
- `ak.wwise.debug.testAssert`
- `ak.wwise.debug.testCrash`
- `ak.wwise.debug.validateCall`
- `ak.wwise.debug.assertFailed` (topic)

Arbitrary Lua is excluded because it recreates model-authored code execution.
Unrestricted UI command registration/execution is excluded because command
add-ons can launch external programs and built-in command IDs can bypass the
packaged project-transition guards. The debug entries are excluded because they are private/internal, change
process-wide behavior, interrupt WAAPI, or deliberately assert/crash Wwise.

## Inspect the exact executable lists

Use the offline catalog instead of copying a static API list into a prompt:

```bash
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 capabilities --limit 0
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 capabilities --route transaction_operation --limit 0
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py --version 2022.1 capabilities --route unsupported_boundary --limit 0
python /absolute/path/to/waapi-skill/scripts/run.py gateway.py describe ak.soundengine.getState --all-versions
```

The catalog and execution registry are tied to an immutable per-version
inventory digest. A URI addition, removal, or same-count substitution fails
closed until the packaged contract is reviewed and updated.

## Verification scope

The focused program gate currently contains 938 passing tests and exercises
all 769 executable version/API rows with
in-process fake clients. It validates exact URI dispatch, reflected request and
result/event schemas, timeout/result ceilings, transaction preparation and
verification, same-connection Undo execution, lifecycle cleanup binding,
isolated path confinement, and topic
subscribe/event/unsubscribe behavior. Separate negative tests cover exclusions,
route bypass attempts, model-authored external command hooks, malformed nested
payloads, and manifest drift. Direct and isolated generic transactions also run
through complete preview/confirm/execute/verify program chains.

This iteration intentionally does not run Codex/OpenCode prompt evaluation,
semantic A/B tests, or the full live-Wwise matrix. Therefore report the result
as “program-tested packaged coverage,” not “769 endpoints live-verified in
Wwise.”
