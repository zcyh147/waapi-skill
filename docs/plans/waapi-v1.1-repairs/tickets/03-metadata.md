# 03: List properties, inspect exact details and page bounded results

## Parent

#163

## What to build

An Agent can list real object/plugin fields, select a returned exact field and inspect it before obtaining a scoped Field Handle for a change.

## Acceptance criteria

- [ ] Expose list and exact-detail contracts using Gateway-owned scope/selection identifiers; mutation still uses Field Handles, never raw native requests.
- [ ] Preserve type, default, constraints, enum choices, dependencies, RTPC support and underlying units. Report missing units as unknown.
- [ ] Bind pagination to scope/version/metadata snapshot, use stable ordering, and prevent omissions, duplicates or cross-scope continuation; diagnose expiry/drift.
- [ ] Make meaning search optional. Narrow exact matches before enforcing output bounds. Large details must have controlled reading or an explicit locatable boundary, not silent truncation.
- [ ] Return bounded per-field rejection reasons; do not present unrelated surviving candidates as the intended field.
- [ ] Complete the public list-to-selection-to-change-to-verification path for all five versions. Record an explicit ADR if exact selection changes an existing input-boundary decision.

## Blocked by

None

## Validation

Gateway fake tests and coordinated real plugin readback: reproduce 39720/33809-byte failure patterns, missing units, unsupported boolean RTPC and cross-scope tokens. Final F1.

## Execution constraints

The user approved implementation on 2026-10-17. All five supported version lanes must be covered; documented native unavailability is an explicit tested boundary, not silent omission. Use the approved public Gateway/FakeClient seams and TDD. Follow repository guidance and the spec budget. Do not modify the Lyra user project or replay its transactions. Report program, real-Wwise and Fresh evidence separately.
