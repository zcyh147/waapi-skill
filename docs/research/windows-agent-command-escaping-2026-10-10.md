# Windows Agent command escaping — 2026-10-10

Research baseline: `c3e68f09`; documentation/source inspection only. No runtime,
Skill, harness, or public-contract edits and no tests or live calls were made.

## Finding and evidence boundary

The proportional first repair is explicit **decoded-string copying** guidance,
with existing exact-copy checks retained, followed by targeted native-Windows
acceptance. Prompt changes can reduce confusion but are not a deterministic
guarantee. Established engineering practice is to keep arguments as data and let
trusted code serialize them at the final process boundary. The reviewed sources
do not establish an industry-wide solution or an effectiveness rate for LLM
command copying.

The [frozen local assessment](windows-expansion-assessment-2026-10-10.md)
distinguishes C06/2022 business success (11 successful authenticated Broker
calls, verified transaction, later exact-copy failure) from both C08 failures
(doubled relative-runner separators rejected before preparation/Preview/Execute;
no mutation). Correct Gateway output is therefore insufficient evidence of
correct Agent transport. These observations establish a failure mode, not its
population frequency. M05 is a separate framework issue and needs no rerun for
this repair.

## Established rules

1. **JSON representation is not the decoded value.** RFC 8259 represents a
   single backslash as `\\` in JSON text. Microsoft documents PowerShell
   single-quoted strings as literal and backslash as *not* its escape character.
   Thus JSON text `".agents\\skills\\..."` decodes to `.agents\skills\...`;
   putting literal `.agents\\skills\\...` inside PowerShell single quotes
   supplies doubled separators. A shell tool's JSON arguments need their own
   JSON serialization; it is the resulting command string that must equal the
   Gateway field. Do not prohibit legitimate JSON escaping at that outer layer.
   [RFC 8259 §7](https://www.rfc-editor.org/rfc/rfc8259.html#section-7),
   [PowerShell quoting](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_quoting_rules?view=powershell-7.5),
   [PowerShell parsing](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing?view=powershell-7.5).
2. **Argument serialization belongs in code.** Python recommends an argument
   sequence; Windows still requires its conversion into a command-line string
   under the target runtime's rules. .NET's `ProcessStartInfo.ArgumentList`
   likewise accepts unescaped values and performs serialization; its first-party
   implementation iterates arguments through `PasteArguments.AppendArgument`.
   Neither is a generic PowerShell/CMD escaping function. Use a pinned executable
   and `shell=False` for the known Python target, not an arbitrary native parser
   or a batch relay. [Python subprocess](https://docs.python.org/3/library/subprocess.html),
   [.NET ArgumentList](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.processstartinfo.argumentlist?view=net-9.0),
   [.NET implementation](https://github.com/dotnet/runtime/blob/d099f075e45d2aa6007a22b71b45a08758559f80/src/libraries/System.Diagnostics.Process/src/System/Diagnostics/ProcessStartInfo.cs).
3. **Pin the shell transport, not merely its name.** PowerShell 7.3 changed
   native argument handling; `Standard`/`Windows` preserve embedded quotes and
   empty strings, while Windows mode retains legacy handling for certain
   executables/extensions. Microsoft specifically cautions about batch-file
   arguments. Preserve the existing attested PowerShell Core/version/mode,
   profile-free wrapper and PS1 relay requirements. [PowerShell parsing](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_parsing?view=powershell-7.5).
4. **Tool schemas do not imply exact-value provenance.** Official OpenAI
   guidance recommends clear formats/instructions and moving known arguments
   into code. Strict function calling enforces its schema; a permissive string
   field can still contain the wrong path. Equality, authority, phase, and
   authorization checks remain application responsibilities. This last point
   follows from the difference between schema validity and comparison with a
   stored expected value. [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling).

## Options for this repository

| Option | Status and benefit | Cost / limit |
| --- | --- | --- |
| Clarify decoded-value copying at continuation use | Fits current interfaces. State that quoted PowerShell arguments preserve backslashes; copy selected decoded field exactly and append only disclosed business parameters for a prefix. | Cheap; behavioral hypothesis requiring fresh evidence. Avoid asking the Agent to run a custom decoder or write code. |
| Improve rendering of selected command | A host renderer could expose the decoded value in a separate tool text block, bound to the same selected field. | Requires renderer integration; do not add an independently selectable command or hand-render from diagnostic argv. Duplicate presentations can introduce disagreement. |
| Generate a slash-neutral runner spelling | Possible bounded change for the fixed current-task Python runner, shared by emitter and exact validator. Removes this particular separator hazard. | Not currently the Windows contract. Prove actual Python launch and exact attested target/cwd. No general slash replacement, UNC/device-path normalization, or business-path rewriting. Microsoft describes namespace-dependent parsing; infer no universal path equivalence from one successful runner launch. [Windows path namespaces](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file). |
| Execute structured argv in trusted host code | Established process-engineering approach; no shell command reserialization by the model. | New host/tool integration. Model-authored argv still needs comparison; the present shell-tool workflow and normal Skill install do not expose this capability. |
| Opaque stored continuation + validated resume | Strongest reduction of known-path/token copying: bind command/runner/phase/argv server-side, let Agent supply a short reference and closed business fields. | New Gateway contract/state lifecycle; needs scoped storage, revision/expiry, tamper/replay protection, executable identity and sandbox checks. Must retain immutable Preview, authorization, execute-once and verification. |
| Bounded pre-dispatch error | Existing Broker rejection contains C08 safely. A future host validator could diagnose an altered prefix before any process dispatch. | Test Broker is not installed in ordinary Skill use; a damaged runner path can fail before Gateway starts. Never repair unknown paths automatically or retry a possibly executed mutation. |

The existing [platform command codec](../../skills/waapi-skill/wwise_waapi/platform_commands.py)
provides an encoded complete-argv `shell_command` and a shorter literal
`model_command`; follow `copy_instruction.source_field`. Microsoft documents
`-EncodedCommand` as UTF-16LE Base64 for nested quoting, not as integrity or
authorization. A copied Base64 string can still be altered. More importantly,
the encoded complete command cannot simply replace `fixed_argv_prefix_copy`:
business arguments are appended to that prefix, and appending tokens outside an
encoded script does not establish equivalent final argv. Long envelopes,
PowerShell discovery, interpreter selection and sandbox admission also need
testing. [Microsoft about_Pwsh](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_pwsh?view=powershell-7.5).

## Recommended repair and acceptance

Start with a short decoded-value instruction in Skill/operate guidance at the
copy boundary; avoid changing closed instruction keys just to add prose.
Example meaning: “Copy the selected JSON string's decoded value. JSON `\\`
represents one backslash; PowerShell single quotes do not unescape it. Preserve
the returned runner, quotes, tokens, and prefix; append only disclosed fields.”
This is proposed wording, not a tested model-specific prescription.

Keep exact-copy admission and posthoc audit unchanged. Focused tests should
cover relative/absolute runner prefixes, exact decoded-string copying, literal
doubled-backslash rejection, complete vs appendable commands, authority-token
length, and unchanged business argv. Existing codec/hostile-JSON transport tests
should preserve spaces, apostrophes, quotes, Unicode, empty values and shell
metacharacters. If rendering changes, prove both host projections and native
PowerShell-to-Python argv on the attested transport, including rejection of
traversal, alternate cwd/runner and token/path substitution.

Then freeze a new candidate and run only C06/2022, C08/2022 and C08/2025 through
the existing Fresh campaign, sequentially on native Windows. Require both exact
transport compliance and verified business effects; retain immutable Preview,
policy/confirmation, at-most-once execution and source/sandbox evidence. A
pre-dispatch rejection may justify a corrected new preparation only when the
existing protocol proves no mutation; ambiguous execution stops for read-only
status/verification, never a speculative retry. A passing targeted sample is
evidence for those paths, not a general reliability claim. Escalate to bounded
runner rendering or stored continuation transport only if failures recur or a
deterministic reliability requirement warrants the interface cost.

## First implementation candidate

The coordinator replaced the existing generic copy sentence in `SKILL.md` with
one short decoded-JSON-value rule and a Windows literal-backslash clarification.
The operate reference remains unchanged: both documents are already close to
their 20000-byte CRLF read budget, and duplicating the instruction would exceed
that bound. No Gateway/Broker schema, renderer, validator, path normalization,
policy or mutation behavior changes in this candidate.

Initial related validation had 600 passing tests and five native-Windows skips;
three documentation-size checks rejected the first wording. After reducing the
change to the Skill entry, all 76 Skill contract/protocol checks passed. Those
selections overlap and do not establish model reliability. Native Windows
Fresh C06/2022 and C08/2022/2025 acceptance is the next required evidence;
no new semantic PASS is claimed by this note.

## Prompt-only result and bounded runner migration

Frozen `791ece941159560cfa410809bd3fd382b63cc5fb`, native-Windows root
`iwin-expansion-791ece94-target3-r1`, did not establish a reliable prompt fix:

- EXP22-C06 reached `verified`, passed all seven independent business assertions
  and all eleven command-copy/provenance checks. Its raw FAIL concerns only
  ancillary notice wording (`visible_preview_notice`, reviewer
  `review_required`, no reviewer error). Business PASS with a nonblocking note;
  that phrase does not justify a repair or another attempt.
- EXP22-C08 again doubled each backslash in the disclosed relative runner.
  Broker call 5 rejected it before preparation; no mutation occurred. The
  earlier absolute bind command was also overescaped. This is an Agent command
  transcription failure, not evidence that Gateway generated the doubled value.
- EXP25-C08 was not attempted after the batch stopped. The root remains frozen
  without verify-only. Both source-project full hashes/mtimes stayed unchanged;
  the owned Scheduled Task and archived launcher copy were removed, with no
  residual process. `coordinator-checkpoint.json` records the closeout.

The next repair changes generated **Python runner locators**, rather than
accepting malformed commands. Gateway emits its owned absolute runner via
`Path.as_posix()` in both diagnostic argv and corresponding command envelopes.
The Broker applies the same canonical spelling to its owned absolute task
runner and emits `./.agents/skills/waapi-skill/scripts/run.py` for the closed
Windows task-local form. Its leading `./` distinguishes Windows bootstrap from
POSIX; using identical constants would select the wrong shell branch.

No arbitrary model path is rewritten. Existing relative-runner admission still
requires the one exact spelling; doubled, mixed, traversing and alternative
relative forms remain rejected. Generic command codecs, business/Wwise paths,
state-directory values, authority tokens, Preview/authorization, execute-once
and verification are unchanged. The encoded audit envelope remains absolute
and agrees with its full argv. This deliberately supersedes the old Windows
backslash-generation policy in `tests/AGENTS.md`. Frozen evidence retains its
original source/contract binding and is not reinterpreted by the new policy.
This removes the runner's JSON backslash ambiguity; it cannot guarantee that a
model never rewrites a command or mishandles a different business value.

Focused validation (separate, overlapping selections; do not sum):

- The new drive/UNC serialization regression first failed twice, then passed
  with the other continuation checks (12 passed). UNC is serialization evidence,
  not a live network-share execution claim.
- macOS affected five-file selection: 1312 passed, 20 platform skips, one stale
  Windows-bootstrap expectation. After updating that fixture, affected command
  checks passed 110 / 5 skipped; additional planning/typed checks passed 99.
- Native Windows transport/continuation selection: 129 passed, 2 POSIX skips,
  one stale generated-runner assertion. The follow-up passed that assertion and
  94 other checks, exposing five instances of the same stale planning assertion;
  the corrected planning selection then passed all 30.
- Native proofs include JSON-decoded command -> profile-free attested pwsh ->
  PS1 relay -> authenticated Broker -> Python, for absolute and task-local
  runners. Appended Unicode, apostrophes, empty values and Wwise backslashes are
  preserved exactly. A separate real Python process opens the forward-slash
  runner locator. Existing hostile-JSON transport checks also pass.

Fresh acceptance is still required for the changed renderer. Select only
EXP22-C06, EXP22-C08 and EXP25-C08 in a new frozen root; C06 is included because
this code change affects its command path, not because of the ancillary notice.
M05 and the other completed business units stay closed. No complete Program or
Non-live pass is claimed from these focused checks.
