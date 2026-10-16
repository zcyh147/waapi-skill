# 08: Remove disposable-test-project cleanup instructions from product outputs

## Parent

#163

## What to build

Normal authoring operations retain the user project and outputs; the test runner alone cleans or quarantines its disposable fixtures.

## Acceptance criteria

- [ ] Remove discard-case-owned-project and seal/never-reuse instructions from normal Gateway results.
- [ ] Audit Preview, success, failure, indeterminate and legacy projections across generate/import/replace and every other exposed operation, not SoundBank alone.
- [ ] Preserve required paired resource cleanup while distinguishing it from deleting projects or outputs.
- [ ] Test lifecycle cleanup remains ownership-based and does not infer project disposability from product receipts.
- [ ] Preserve historical and failure evidence; classify license prerequisites independently. Cover all five version lanes and result phases.

## Blocked by

None

## Validation

Public output tests for persistent projects across terminal states and import/replace/generate; regression tests for test-owned cleanup. No additional Fresh.

## Execution constraints

The user approved implementation on 2026-10-17. All five supported version lanes must be covered; documented native unavailability is an explicit tested boundary, not silent omission. Use the approved public Gateway/FakeClient seams and TDD. Follow repository guidance and the spec budget. Do not modify the Lyra user project or replay its transactions. Report program, real-Wwise and Fresh evidence separately.
