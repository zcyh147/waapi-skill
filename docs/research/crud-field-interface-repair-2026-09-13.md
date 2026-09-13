# CRUD field Interface repair — 2026-09-13

Baseline: `2c714912e8383538290dd46fd61af56526c8e4fe`.
Branch: `codex/harden-batch-field-diagnostics`.
Scope follows the [audit plan](crud-interface-closure-audit-plan-2026-09-13.md)
and [five-version partition](crud-five-version-evidence-audit-2026-09-13.md).
The earlier audit documents describe the pre-repair state; their source line
references should be interpreted in that historical context.

## Implemented

- **F1, batch selection:** `object.set` batch `--field` is a strict fixed-field
  input. Unknown names return `UNKNOWN_BUSINESS_FIELD` with the row identifier,
  rejected field, disclosed choices and unchanged-Draft indication. Dynamic
  batch values now use `--field-value ROW FIELD_HANDLE VALUE`. The old
  `--field-meaning-value` mutation input and its internal search/selection path
  were removed. Field discovery remains available after binding multiple
  objects; each dynamic handle must match its exact row object. The entire
  declaration still commits atomically and follows normal check/Preview.
- **F2, acquisition:** public `draft-bind-field`, its token/class flags, its
  dispatch handler and Adapter opt-ins were removed. Import now uses the
  existing field discovery with an object handle or closed semantic kind;
  creation/plug-ins continue using their existing kind/type-handle discovery.
  `bind_live_field` remains an internal metadata-validation primitive, not a
  second model-facing input path. A packaged-tree search found no remaining
  `draft-bind-field`, `field-meaning-value` or `supports_field_binding` entry.
- **F3, common values:** a small shared field-definition module supplies the
  common graph/import vocabulary. Graph declarations expose `fade_time_ms` and
  `delay_ms` for Action objects and compile them to existing native seconds
  fields. These fixed Action fields are not added indiscriminately to import
  rows or other object types. All dynamic field-value entrypoints use the
  same parser; time suffix conversion is Action-scope-aware, including rejection
  of a plug-in merely named Action. Discovery discloses the bare-number unit
  for supported Action durations. `volume_db` remains implemented as before.
- **F4, enum values:** bounded enum labels are preserved in the existing field
  restrictions. Unambiguous exact labels can be used as values. Duplicate labels
  and label-versus-value collisions fail explicitly; returned `value_input`
  choices provide copyable `choice:<index>` inputs scoped by the accompanying
  field handle and its metadata snapshot. No separate choice store was added.
  Existing serialized fields without optional labels remain readable.
- **Diagnostics:** zero-match field discovery identifies the requested meaning,
  owning object handle, candidate count, scan completeness and unchanged-Draft
  status. Multiple matches remain explicit candidate sets requiring selection;
  they are not auto-guessed into a write. Counts refer to returned compatible
  candidates, not an unbounded exhaustive property search.

No new native URI, authorization mode, execution retry, Preview state machine,
or Wwise verifier was introduced. Common field naming is not permission to skip
the existing live property/dependency checks at Preview and execution.

## Regression and evidence

All invocations ran locally on macOS with the Poetry-backed test driver.
They used fake clients and temporary state, not the demonstration project.

| Run | Result | Interpretation |
| --- | --- | --- |
| Initial unknown-fixed-field tracer, 2022–2025 | 4 failed | Demonstrated that the old batch accepted `Action Fade Time` as an unrecognized fixed name by searching for a field. |
| After strict fixed-field change | 4 passed | Same public Gateway regressions now reject before property discovery. |
| New field Interface regression file, final | 53 passed | Acquisition, exact handles, batch atomicity, enum labels/ambiguity, Action units, wrong object/type, invalid durations, five-version single-field behavior and four-version fixed-field Preview. |
| Post-Non-live targeted selection | 146 passed | New Gateway tests, Skill routing/size contracts, original two failed documentation assertions, and interface inventory checks. Four later wrong-object cases were additionally covered in the final 53-case file and Program gate. |
| **Final fixed five-version Program gate** | **5011 passed, 2 skipped** | Exit 0, 201.58 s. Native Windows shell/junction proofs were skipped, not credited. Includes the new 53-case file. |
| Full Non-live run, before final diagnostic/test-only cleanup | 10598 passed, 2 failed, 113 skipped, 27 deselected | 687.17 s. Both failures were old operate-reference assertions; one explicitly required the retired no-discovery batch rule. They were corrected and passed in the targeted selection. Do not relabel this original full run as all-pass. |

Commands:

```sh
ci/test.sh --mode nonlive -- tests/unit/test_field_interface_closure_gateway.py -q --tb=short
ci/test.sh --mode program -- -q -ra --tb=short
ci/test.sh --mode nonlive -- -q -ra --tb=short
```

The four-version fixed-duration tracer goes through the public declaration,
`draft-check` and `preview-from-draft`; it asserts an immutable transaction was
created and no `ak.wwise.core.object.set` dispatch occurred. It proves program
construction/Preview, not actual Wwise effects. Earlier fixture-only failures
(state directory placed inside the fake project, and assuming Preview replies
contain a Draft receipt) were corrected in the local test fixture, not in the
production protection rules.

Earlier exploratory Program runs remain failed evidence: 4999 passed / 2
failed / 2 skipped, then 5001 passed / 1 failed / 2 skipped. Their failures were
a removed Adapter attribute assertion and wording/size assertions after routing
was revised. The final run above supersedes them for Program acceptance.

The full Non-live suite was not repeated merely for the two corrected prose
assertions. Subsequent runtime changes were confined to enum ambiguity
diagnostic counting and stale CLI help wording; final Program and focused
regressions cover them. The final eight added Preview/wrong-object tests are
included in the 53-case and final Program results, not retroactively in the
earlier full Non-live total.

The generic skill-creator validator could not start because the locked Poetry
environment lacks `yaml`/PyYAML. No dependency was installed. Repository Skill
protocol, gateway-contract and reference-size checks passed instead. This is
not a claim that the generic validator ran successfully.

## Deliberate limits

- No Fresh Agent, actual Wwise/Console, native Windows, new version reflection
  or weather re-import was run. Historical live results remain attached to
  their own candidates. The existing native FadeTime/Delay representations are
  reused; this change does not claim new exhaustive live ActionType/plug-in or
  per-version property coverage.
- R1 ordinary object-list selection remains the existing exact-user-owned-name
  contract with strict list readback and dedicated RTPC/Effect boundaries. The
  audit identified a design concern, not a proven incorrect write; no invented
  list inventory or broad list-state rewrite was added.
- Read-only field-meaning searches remain read-only. They do not authorize a
  mutation and were not forced into the Draft lifecycle.
- No state-directory move, whole-store migration, current demonstration reset,
  installed Skill synchronization, old-transaction replay, merge or push.
  The user's unrelated article fact-check file was preserved outside the staged
  change. Old sealed test evidence remains unchanged.

This closes the four confirmed repair items within the stated Interface scope;
it is not a claim that every WAAPI scenario or model intent is now infallible.
