# 07: Continue recoverable workflows within the selected modification policy

## Parent

#163

## What to build

Agents can refine queries, page or reconnect after side-effect-free errors without repeated permission prompts, while uncertain writes are never blindly replayed.

## Acceptance criteria

- [ ] Unify Skill/reference instructions and Gateway recovery receipts; remove the blanket stop-after-any-error rule.
- [ ] Keep read_only, ask_before_changes and allow_changes as permission authorities. Service startup must remain within the existing task authorization.
- [ ] Distinguish pre-dispatch rejection, read failure, known write outcome and unknown write outcome, and disclose actionable next steps.
- [ ] Allow independent read-only diagnosis after indeterminate when authorized; never replay the original write or infer success/no change from an error string.
- [ ] Update semantic judgments so legitimate discovery refinement is accepted; preserve historical raw verdicts. Cover policy behavior on all five versions.

## Blocked by

None

## Validation

Three-policy Gateway/fake-failure and harness negative tests. Final F2; F1/F3/F4 also observe that needless permission stops are absent. No additional Fresh.

## Execution constraints

The user approved implementation on 2026-10-17. All five supported version lanes must be covered; documented native unavailability is an explicit tested boundary, not silent omission. Use the approved public Gateway/FakeClient seams and TDD. Follow repository guidance and the spec budget. Do not modify the Lyra user project or replay its transactions. Report program, real-Wwise and Fresh evidence separately.
