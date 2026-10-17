# 05: Complete GameParameter creation with range and default configuration

## Parent

#163

## What to build

Creating a GameParameter with minimum, maximum and default values has an executable public workflow without asking for an object that does not yet exist.

## Acceptance criteria

- [ ] First use the established deterministic sandbox test lifecycle to establish whether same-call creation/configuration is supported and under which dependency conditions.
- [ ] If supported, implement new-object dependency validation; otherwise expose explicit phases, each with its own Preview, authorization and verification.
- [ ] Return an actionable successor for dependent class-field failures instead of merely suggesting another search term.
- [ ] Report partial creation/configuration accurately, avoid duplicate objects on continuation, and never append undisclosed writes after Preview.
- [ ] Independently read back range/default values; preserve existing-object configuration. Cover all five versions, including native differences and explicit boundaries.

## Blocked by

#166

## Validation

Gateway fake tests for FIELD_OBJECT_SCOPE_REQUIRED, partial failure and all three modification policies. Coordinated deterministic live evidence; final F3.

## Execution constraints

The user approved implementation on 2026-10-17. All five supported version lanes must be covered; documented native unavailability is an explicit tested boundary, not silent omission. Use the approved public Gateway/FakeClient seams and TDD. Follow repository guidance and the spec budget. Do not modify the Lyra user project or replay its transactions. Report program, real-Wwise and Fresh evidence separately.
