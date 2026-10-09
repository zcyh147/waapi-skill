# Windows notice-review stdin repair — 2026-10-10

Base candidate: `a898d8d8671ec29566f6f2406a7d29f495c4ee76`.
This changes the semantic harness only; the packaged Skill is unchanged.

## Failure and repair

`iwin-expansion-a898d8d8-c01-r1` passed exact Skill/reference reads but stopped
at Preview. Its review receipt had `judgment=null` and `WinError 206`, not a
negative language judgment. The complete review JSON exceeded Windows argv
limits. C03/C06 also retained raw FAILs before the owner stopped the batch;
C08 was interrupted and no positive business result is claimed for those units.
The owner sealed 1324 files, proved both source hashes/mtimes unchanged and
reported zero residual scoped processes. Both roots stay frozen.

Invocation v3 uses a context-only CLI prompt audit, then `codex exec -` with
canonical UTF-8 bytes on stdin. CLI 0.162.0 `debug prompt-input -` does not read
stdin, confirmed by a marker probe; using it for the packet would silently audit
a literal dash. The existing bounded process runner supplies a private input
handle and records SHA-256 and length. Input remains capped at 131072 bytes;
output, deadlines, isolation, rubric, judgment grounding and verification gates
are unchanged. Replay requires the exact prelaunch transport binding and
process input evidence. Historical v1/v2 bindings retain argv semantics.

## Completed validation

- macOS affected harness, review, archive, task, discovery and authorization
  files: **3080 passed, 14 skipped** in 35.95 seconds.
- Initial native Windows review-file selection: **304 passed, 1 skipped,
  6 setup/teardown errors** in 125.43 seconds. Three new parameter values became
  huge pytest IDs and exceeded native path constraints. Explicit short IDs
  fixed test naming without shortening tested inputs.
- Final targeted stdin/legacy replay/current audit selection: **13 passed,
  74 deselected** on native Windows (4.75 seconds) and macOS (0.63 seconds).
  This includes exact child stdin larger than 32767 UTF-16 units, the 131072-byte
  bound, Chinese/quotes/CRLF, input-tampering rejection and legacy replay.
  These overlap prior selections; do not sum them or claim a full Non-live gate.
- Real native CLI 0.162.0 independent-review diagnostic used the original C01
  packet in a separate root, `C:/w/reviewer-stdin-diagnostic-r1`. All **57358
  UTF-8 bytes** were supplied through stdin. Audit argv was 4723 UTF-16 units;
  execution argv was 5130. Reviewer completed in **42.806444 seconds**, exit 0,
  accepted, and receipt replay succeeded. Model remained `gpt-6.1-sol`, high,
  default. This proves reviewer transport and execution only; it neither
  regrades the frozen case nor grants business PASS.

The native diagnostic checkout is `C:/w/review-stdin-fix`. Its receipt binds
actual source/runtime hashes. A subsequent fresh clean candidate must prove
C01's complete business chain before the remaining batch resumes.

## Execution ownership

The user authorized the Mac coordinator to own Windows runs through SSH and
existing `InteractiveToken` / `Limited` Scheduled Tasks. Desktop cross-thread
messaging is not required: read campaign logs, receipts and sealed outputs
through SSH. Do not run concurrent owners. The formal Fresh campaign remains
the sole semantic harness; ordinary pytest remains direct SSH. Inspect a
failed notice receipt before treating it as ordinary wording. A failed reviewer
launch is infrastructure failure and stops affected work.
