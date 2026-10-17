# 02: Use configuration-only connections throughout Gateway workflows

## Parent

#163

## What to build

A user configures the endpoint and expected version once; every public read and mutation uses that configuration, and existing Drafts/transactions cannot silently change projects.

## Acceptance criteria

- [ ] Remove ordinary online host/port/version flags and connection-environment overrides. Keep config-set and explicitly offline version browsing. Apply to Draft, inline, zero-input, query and Topic paths.
- [ ] Explain independent configuration selection: copying a Skill directory alone does not isolate the existing user-level configuration.
- [ ] Persist initial endpoint/version binding in the Draft; bind live project GUID and version/build on first live use, then carry identity through immutable Preview and transaction records.
- [ ] Compare current configuration with stored binding before business dispatch. Configuration, actual version or project changes must fail explicitly, without silent fallback.
- [ ] Cover CLI restarts, old records lacking bindings, all continuations and migration of test launchers/harnesses to isolated config files.
- [ ] Update public help, schema, Skill guidance and relevant architecture/configuration rules. Implement and program-test all five supported versions.

## Blocked by

None

## Validation

Public Gateway end-to-end fake tests across five versions, including Windows command forms. A coordinated sandbox read validates the actual connection; never contact another user project. F1–F4 reuse this route, with no extra Fresh.

## Execution constraints

The user approved implementation on 2026-10-17. All five supported version lanes must be covered; documented native unavailability is an explicit tested boundary, not silent omission. Use the approved public Gateway/FakeClient seams and TDD. Follow repository guidance and the spec budget. Do not modify the Lyra user project or replay its transactions. Report program, real-Wwise and Fresh evidence separately.
