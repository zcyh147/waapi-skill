# Windows expansion portability repair — 2026-10-10

Base: `9589659ede2fa025c7eabdba0154e2e6155b923a`. Development checkout:
`C:/w/exp-winfix-958`, native Windows via SSH. The packaged Skill is unchanged.
This is program/harness evidence, not real Agent acceptance or an all-green
Non-live claim. Exact logs, digests and the 34-file selection are in the
[record](windows-expansion-portability-2026-10-10.json).

## Findings and repairs

- Git CRLF conversion changed hash-pinned semantic fixtures. Pin their committed
  bytes with `-text`; never normalize bytes during evidence verification.
- Non-live child Python now explicitly uses UTF-8. Localized `taskkill`
  diagnostics use the Windows OEM decoder with replacement; Agent/evidence
  decoding stays strict, and process exit remains the cleanup authority.
- Native file enumeration omitted identity fields, and Windows handle/path
  metadata exposed different ctime semantics. Use `lstat` consistently; retain
  ctime for path-to-path checks and dev/inode/mode/size/mtime for handle checks.
  Full byte hashing, bounds, reparse checks and replacement rejection remain.
- Fake reviewer runtimes now use the required standalone Windows layout.
  Synthetic archive writers use the production UTF-8 byte writer, native runner
  paths and exact task-local command constants. Historical archives are untouched.
- Archived import parameters use the existing explicit path-flavor parser.
  POSIX witnesses remain POSIX data on Windows. Fake native I/O roots and command
  expectations match the current closed interface.
- Compact business-response tests exclude the variable-size host continuation;
  exact continuation and Gateway delivery-ceiling tests remain separate.
- Fake subscription writers remain alive for native parent-process attestation.
  Missing symlink privilege skips only the symlink subcase, not regular-file tests.
- Music fixture preparation now rejects case aliases by exact spelling on both
  hosts; native case-insensitive `Path` equality previously hid that collision.

## Completed checks

| Run | Result |
| --- | --- |
| Original Windows Non-live, before repair | 16309 passed; 750 failed; 49 errors; 266 skipped; 27 deselected |
| Windows: all 34 originally failing files, intermediate repair | 3525 passed; 30 failed; 15 skipped; 5 warnings; 741.44 s |
| Windows: those 30 failures plus affected boundary checks, final repair | 122 passed; 1 failed; 28.46 s; thread warnings promoted to errors |
| macOS: archive/reviewer/affected unit checks | 636 passed; 1 skipped |
| macOS: path, source guard, process cleanup and launcher | 90 passed |
| macOS: command/media/first-use checks | 49 passed |
| macOS: heavy protocol fixtures | 186 passed |
| macOS: final archive/rejected-check/music fixture checks | 263 passed |

These selections overlap; do not sum them as unique coverage. No Wwise process
or paid Agent was started by these repairs. No second full Non-live or macOS
Fresh campaign was run.

One raw failure remains: `test_native_windows_powershell_shim_preserves_public_typed_container_facts`.
It expects the retired `draft-apply` Composer path for `soundbank.setInclusions`;
the current protocol uses bound business declarations, so `max(empty)` fails
before any shell or Gateway call. Keep this visible as a stale, nonblocking
transport-test fixture; its migration is outside the expansion assessment.
The existing native hostile-JSON transport tests passed in the 34-file run.
This exception grants no missing transport or semantic coverage.

## Resume boundary

The original `iwin-expansion-9589659-sol-high-r1` remains frozen. Its CLI/model
block and interrupted preparation grant no positive-case PASS credit. CLI
0.162.0 has since passed the owner's minimal `gpt-6.1-sol / high / default`
probe. Continue the authorized 13 positive units and separate EXP22-M05 boundary
in a fresh clean candidate checkout and new campaign root. Keep the executor
and reviewer settings, sequential execution, source protection and business-first
reporting from [TEST_ACCEPTANCE](../../tests/semantic/TEST_ACCEPTANCE.md).
Do not resume or regrade the old root. Ordinary failures are collected through
the batch; source, authorization, evidence or cleanup faults stop affected work.
