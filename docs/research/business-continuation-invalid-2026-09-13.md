# Installed-Skill import continuation failure — 2026-09-13

## Finding

Repair candidate: `3c8b63b45bf1f62e874b6bb23c08250c9320e415`.
Baseline: `0a2341c1ccdba13510843a2d0630c6b9d80f7d16`.
The working branch includes the earlier, still-unmerged welcome changes.

The macOS demonstration used Wwise Authoring 2024.1 and, per the operator,
Sol / High in separate tasks without an injected memory summary. The installed
Skill was `/Users/xiye/Documents/Git/waapi_skill_test/.agents/skills/waapi-skill`.
Its relevant Gateway, planning, and import compiler files matched the repository
baseline when inspected; this was not a stale-copy explanation.

| Recorded task | Public revision at check | Internal business revision | Outcome |
| --- | ---: | ---: | --- |
| Weather `01a096db-8cfb-73a3-96fe-509a445c8987` | 6 | 9 | BUSINESS_CONTINUATION_INVALID |
| Snow `01a096e0-251b-70b2-be7d-06e24215adea` | 3 | 5 | BUSINESS_CONTINUATION_INVALID |
| Alarm `01a096dd-aecc-7b23-9966-20258d6e78aa` | 5 before successful check | not implicated | object.setReference executed and verified |

## Complete failing chain

1. Gateway accepts object bindings and import declarations. Weather supplied
   nine declarations in two chunks; Snow supplied five in one chunk.
2. `draft-check` materializes the exact public Draft revision, revalidates
   live identities and metadata, then calls the audio-import preview compiler.
3. That compiler calls `compile_business_plan`, whose callback uses
   `transaction_next_command` to generate the next `preview-from-draft` command.
4. In this installation and working directory, Gateway publishes the fixed
   `.agents/skills/waapi-skill/scripts/run.py` copy path while retaining an
   absolute runner in `full_argv` for audit.
5. The planning validator still required `shell_command == shlex.join(full_argv)`.
   It rejected its own Gateway's valid short command and wrapped the ValueError
   as BUSINESS_CONTINUATION_INVALID. No executable Preview was produced.
6. The error used the internal business session's revision (9 / 5), rather than
   the public Store revision (6 / 3). The original records remain editable,
   with `check: null` and unchanged public revisions. The discrepancy is not
   evidence of a concurrent update or an Agent-authored revision mistake.

Alarm does not use the audio-import preview compiler, so its successful
object.setReference path does not exercise this failing validator.

## Why previous automation missed it

The short-runner generator and planning validator had separate tests. The
planning tests supplied absolute-path continuation examples rather than passing
the real Gateway-produced task-local form into the compiler.

The Fresh Broker also distinguishes the Agent-visible installation from its
trusted runner. It executes `self.runner_path` with `runner_cwd` defaulting to
the source Skill directory, then projects commands for the Agent. That layout
does not normally trigger the installed-workspace short-runner branch inside
the production compiler. Previous passing business outcomes therefore did not
prove this deployment-layout combination.

## Minimal repair

- `platform_commands.encode_posix_gateway_argv` owns the existing exact
  task-local shortening rule. Gateway generation and business-plan validation
  now use the same function; no second path-equivalence algorithm was added.
- Only the fixed runner under the current workspace can shorten. Interpreter,
  Gateway marker, every argument, quoting and revision remain exact. The
  existing absolute audit spelling stays valid. Windows encoding is unchanged.
- At the public Gateway compiler boundary, existing
  `repair_at_draft_revision` maps nested errors back to the public Draft
  revision. No state-machine phase, storage field, expiry, authorization,
  execution rule or retry behavior changes.

## Verification

The new producer-to-validator regression first failed with the same
BUSINESS_CONTINUATION_INVALID. The public Gateway chain likewise failed in the
task-local layout; a deliberately invalid continuation exposed the erroneous
internal revision. Both became green after repair.

| Check | Result | Scope |
| --- | --- | --- |
| macOS focused four-file regression | 317 passed, 1 skipped | Compiler, import Gateway, transactions and command envelopes |
| macOS Program gate | 4791 passed, 2 skipped | Fixed fake-client gate; no Wwise or Codex |
| Windows focused bug-specific selection | 102 passed | Same candidate; real native Python/PowerShell, fake Wwise clients |
| Windows broader four-file selection | 312 passed, 5 skipped, 1 failed | Existing summary-size assertion, detailed below |
| Weather/Snow real demonstration reruns | Not run | No new Fresh task or live import attempt was started |

The focused compiler matrix covers all five supported versions and rejects
altered runner paths, absolute bindings, working directories, revision values,
and shell suffixes. The public Gateway test proceeds from a new temporary Draft
through check and immutable Preview, using fake clients that reject unexpected
WAAPI calls. Invalid continuations leave the Draft bytes unchanged and report
the public revision. These are program tests, not real Wwise acceptance.

Windows ran only ordinary program tests directly over SSH, using the existing
Poetry developer Python selected through `WAAPI_TEST_PYTHON`. Two temporary
detached worktrees isolated the repair candidate and baseline. No Scheduled
Task was needed: neither Codex/Fresh Agent nor Wwise was launched.

The additional Windows failure was
`test_transaction_show_summary_omits_raw_artifact_bulk_but_keeps_review_evidence`:
7180 bytes against a 5500-byte assertion. The identical test also failed on the
baseline (7182 bytes). It is recorded as pre-existing and was not relaxed or
fixed in this change. The broader Windows selection is not an all-pass result.

## Preservation and handoff

Failure evidence is retained in ignored
`skills/waapi-skill-workspace/continuation-demo-20260913/`: redacted task traces,
original Draft records, original installed runtime files, and Windows terminal
results. Thread-retrieval truncation flags remain intact; they are not treated
as evidence that the original Agent's tool output was truncated.

Original record SHA-256 values, rechecked after synchronization:

- Weather: `4c69f676593c2babedf4d3558eaeb23c23dd2f96266b8b8e0f2bd3eea58cc2c6`
- Snow: `29c45269b2f508a94db73d8441d39ae4f0058cbf89a915a40aaf080296714e51`

The three repaired runtime files were synchronized to the demonstration Skill
and compared byte-for-byte with the tested source. The old Drafts were not
replayed, canceled, migrated or edited; no demo project/config/media was reset
or changed by this repair task. Any subsequent demonstration should start a
new task and a new Draft, with the intended modification policy checked
explicitly. Alarm's recorded task changed shared configuration to
`allow_changes`; that observation is separate from this continuation defect.
