# Windows validation after macOS Wwise WAAPI work

## Purpose

Use this handoff when macOS Wwise WAAPI work is complete and Windows compatibility still needs proof. The goal is to validate the existing skill on a real Windows host without depending on a committed `AGENTS.md` or any global agent instructions.

Do not treat macOS results as Windows evidence. macOS Wine results give useful confidence, but they are not a substitute for explicit Windows validation.

## Current macOS baseline

The current macOS baseline passed the full composite matrix:

```bash
ci/test.sh --version all --mode all -- -q -ra
```

Recorded result:

- nonlive matrix: `756 passed, 60 skipped, 21 deselected`
- strict real Wwise matrix: `32 passed`

This means the shared WAAPI behavior, test sequencing, and live destructive gates have a strong macOS signal. It does not mean Windows has passed.

## Why Windows still needs a real run

On macOS, Wwise runs through Wine. Once Wwise is launched and WAAPI is reachable, much of the Wwise-internal behavior is expected to be close to native Windows behavior. WAAPI request shapes, object mutation behavior, schemas, and event semantics should usually be validated by the same live matrix.

The remaining Windows risk is mostly outside the WAAPI layer:

- launching `WwiseConsole.exe`
- resolving `%WWISEROOT%`
- handling backslashes, drive letters, and paths with spaces
- cleaning up Wwise processes with Windows tools such as `taskkill`
- avoiding file lock issues after project open, mutation, and close
- handling Defender or firewall prompts around WAAPI ports
- shell differences between Bash, Git Bash, PowerShell, and `cmd.exe`
- matching the expected Python and Poetry environment on the Windows host

Windows should be validated explicitly because these launch, path, cleanup, filesystem, and environment issues can fail before the code reaches normal WAAPI behavior.

## Windows prerequisites

Run from a Windows host with the repository checked out locally. Do not use stale macOS evidence, a copied evidence directory, or Wine output as proof.

Required setup:

- Wwise versions intended for the matrix are installed, including the configured 2021.1, 2023.1, 2024.1, and 2025.1 targets when available.
- `%WWISEROOT%` resolves to the active Wwise installation root, and `%WWISEROOT%\Authoring\x64\Release\bin\WwiseConsole.exe` exists for the version under test.
- Python and Poetry are installed and available in the shell used for the run.
- A project-supported Bash environment is available for `ci/test.sh`, such as Git Bash.
- Defender, firewall, or corporate endpoint tooling will allow Wwise WAAPI server startup and local port access.
- No unrelated Wwise, WAAPI, or helper processes are running before the matrix starts.

If a prerequisite is not true, fix it or record the exact blocker. Do not mark Windows validation as passed from a partial setup.

## Commands

From the repository root on the Windows host, run:

```bash
ci/test.sh --version all --mode all -- -q -ra
```

This should run nonlive coverage first, then the strict real Wwise matrix. It should cover all configured versions and modes available to the project.

If the shell cannot run `ci/test.sh` directly, use the closest project-supported Bash environment and record the shell in the evidence. Do not replace the command with a narrower pytest invocation unless you clearly mark the result as partial and keep Windows validation pending.

## Expected results

A successful Windows validation needs all of the following:

- The full `--version all --mode all` command exits with status 0.
- The output shows nonlive tests ran before real Wwise tests.
- Real Windows launches used `WwiseConsole.exe`, not macOS Wine paths or copied logs.
- Skips are expected and reviewed. No skip hides a Windows launch, path, firewall, file lock, cleanup, shell, Python, or Poetry problem.
- Destructive or real-mode tests leave source fixture projects clean.
- No Wwise, WAAPI, or helper processes remain after the matrix finishes.
- Temporary projects, generated files, locks, and evidence artifacts are either expected or cleaned up.

Passing only the macOS baseline, only nonlive tests, or only a subset of live versions is useful evidence, but it is not enough to close Windows compatibility.

## Failure triage

Use the failure location to narrow the cause before changing code.

- `WwiseConsole.exe` not found: check `%WWISEROOT%`, installed Wwise versions, and whether the expected `Authoring\x64\Release\bin` path exists.
- Path parsing or project open failures: check backslashes, drive letters, spaces in paths, quoting, and whether arguments are passed as one argv element instead of one shell string.
- Process cleanup failures: check for leftover Wwise processes and whether `taskkill` is available and allowed by policy.
- WAAPI connection timeouts: check firewall prompts, Defender blocks, port conflicts, and whether Wwise launched but did not expose WAAPI.
- File lock or cleanup errors: close Wwise, remove stale temp projects only after confirming they are not source fixtures, then rerun from a clean state.
- Shell failures: record whether the run used Git Bash, PowerShell, or `cmd.exe`; prefer the project-supported Bash path for `ci/test.sh`.
- Python or Poetry failures: confirm the active interpreter, Poetry environment, and dependency install are from the Windows checkout, not a macOS path or copied virtualenv.

Do not translate a failing Windows run into a passing claim by dropping versions, modes, destructive gates, or evidence checks.

## Evidence review

After the command exits, review the output and generated evidence before updating any status:

- Confirm the run happened on Windows and used real Windows paths.
- Confirm launch evidence shows `WwiseConsole.exe` for the intended Wwise versions.
- Confirm no hidden skip or xfail masked a Windows-specific failure.
- Confirm source fixture projects remain unchanged after destructive-mode tests.
- Confirm no Wwise, WAAPI, helper process, temp project, lock file, or unexpected generated artifact remains.
- Preserve enough command output, shell details, environment notes, and failure logs for a future human or AI to understand the result without global instructions.

If evidence is missing or ambiguous, leave Windows validation pending or failed.

## Done criteria

Windows compatibility can be marked complete only when:

- the full Windows-host command above passed,
- evidence proves real Windows `WwiseConsole.exe` launches,
- skips and failures were reviewed and do not hide Windows-specific issues,
- source fixtures and cleanup checks are clean,
- the Windows gate or status is updated only from this Windows-host evidence.

Until then, say that Windows validation is pending. Do not claim Windows has passed from macOS Wine, from partial Windows runs, or from unreviewed copied evidence.
