# Portable Skill entry — 2026-09-14

Baseline: `main@1e54f8a`, original `v1.0.0`. The user approved updating that
not-yet-distributed release only after the replacement passes validation.

## Scope

The description now uses user-facing query/edit/subscribe/monitor verbs and
contains no agent brand or shell bootstrap. The entry resolves scripts and
references from the supplied Skill root, reuses complete host-loaded text,
and requires complete UTF-8 reads. The Windows task-relative `.agents` path
and public 267 retry exception were removed; the operate reference no longer
mandates POSIX `cat`. Historical Codex test names remain truthful provenance.
Gateway-only operations, exact continuation copying, authorization, immutable
Preview, execute-once, verification, bounded results and failure stops remain.

No WAAPI builder, dispatch, business parameter, or transaction implementation
changed. This is not a claim of execution on every agent client or installation
layout. The formal harness still owns a task-local installation. Fake read-audit
regressions additionally cover exact nonstandard roots, unrelated working
directories, spaces and Unicode; those are not Fresh-client installation proof.

## Initial candidate and retained failures

Candidate `aa81731938e3c4a5ac22050898af267a26f36225` ran two bare first-use
tasks per host, with space-containing roots, Terra/medium/default, memory off,
and no bootstrap hints. Both hosts froze **0/2 PASS** under the old grader;
no failed root was replayed or relabeled.

- macOS root: `/Users/xiye/.local/share/waapi-entry-aa81731/skills/waapi-skill-workspace/entry first use aa81731 r1`.
  Both tasks read all 223 Skill lines through `sed -n '1,240p'` and then made
  exactly one successful offline `config-show`, with correct welcome facts.
  The read audit rejected the numeric complete range. One welcome's
  “尚未确认已连接” was also misclassified as an affirmative connection claim.
- Windows root: `C:\w\entry-aa81731\skills\waapi-skill-workspace\entry first use aa81731 r1`.
  Both tasks read the complete Skill through attested PowerShell Core
  `Get-Content -Raw`, then made one successful `config-show` and introduced
  its facts. The old audit required the redundant explicit encoding flag;
  one also used valid forward separators. The same negation mismatch affected
  one welcome. Its 513 manifest hashes matched; the one-shot
  InteractiveToken/Limited task was removed and owned residuals were zero.

Those first-turn failures prevented the wait/no-repeat follow-up turns from
running. Functional first-turn observations do not substitute for a completed
two-turn PASS.

The first Program gate at this candidate returned **5761 passed, 5 failed,
2 skipped**. All five failures asserted retired entry wording, a two-line
plain-only YAML shape, or old sentinel phrasing. The affected public document
contract files passed **83 tests** after aligning those assertions with the
approved complete-load and folded-description contract.

## Narrow audit corrections

- Numeric `sed -n '1,Np'` is accepted only for an approved exact source when
  N covers the entire file and the complete output matches trusted UTF-8 text.
  Partial ranges, extra expressions/operators, stale paths and corruption
  remain rejected, including for lane references and their sentinels.
- `Get-Content -Raw` may use the UTF-8 default only inside the existing sealed,
  profile-free PowerShell Core wrapper with full trusted-content comparison.
  Canonical forward/backslash read paths must still resolve to that exact
  source. Legacy/unattested shells and other explicit encodings remain rejected.
  [Microsoft's Get-Content contract](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/get-content?view=powershell-7.5#-encoding)
  specifies the Core default as UTF8NoBOM. This changes file-read grading only,
  never Gateway continuation serialization or copy integrity.
- A narrow adjacent negated-confirmation expression handles “尚未确认已连接”
  and equivalent confirmation/verification variants. A separate affirmative
  connection claim still fails; this is not a general free-form language judge.
- A bare Markdown Skill link wraps destinations containing spaces or
  parentheses in `<...>`; ordinary no-space prompts remain byte-identical.

All changes have RED/GREEN regressions. The complete owned first-use/harness
test files passed **355 tests, 9 native-Windows-only skips**. The Skill format
validator passed. The initial two portability document tests also reproduced
the old interface before the edit and passed afterward.

## Final validation

Pending: new frozen candidate, both platforms' `first_use_2`, one unhinted
offline C1 coverage-reference task per host, and final Program/Non-live gates.
First-use has no replay path. C1 may receive its identical verify-only audit.
No real Wwise process, full Fresh matrix or project mutation is in scope.
