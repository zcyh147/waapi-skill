# 01: Audit all public branches and the ShareSet coverage omission

## Parent

#163

## What to build

Build a reproducible five-version branch ledger and establish why standalone ShareSet creation was omitted from earlier coverage claims.

## Acceptance criteria

- [ ] Reconcile functions, Topics, schema fields/enums/unions/nested collections and the narrow Authoring overlay for every supported version: 2021.1, 2022.1, 2023.1, 2024.1 and 2025.1.
- [ ] Add source-backed business combinations: target type, placement, operation mode and version differences. URI presence or structural parity alone is not full business coverage.
- [ ] For each row record public contract, compiler, preflight boundary, verifier, program/live/Fresh evidence separately, and unknowns. Detect same-count URI substitutions and unmapped branches.
- [ ] Trace the ShareSet omission through historical inventories, implementation and test evidence; report demonstrated causes, not speculation.
- [ ] List additional gaps with severity and evidence; do not silently expand this implementation scope or mark missing supported behavior as prohibited. Reconcile the final ledger after repairs.

## Blocked by

None

## Validation

Offline generator/checker and negative controls for the known ShareSet omission and removed mappings. No Fresh.

## Execution constraints

The user approved implementation on 2026-10-17. All five supported version lanes must be covered; documented native unavailability is an explicit tested boundary, not silent omission. Use the approved public Gateway/FakeClient seams and TDD. Follow repository guidance and the spec budget. Do not modify the Lyra user project or replay its transactions. Report program, real-Wwise and Fresh evidence separately.
